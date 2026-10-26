"""聚合音乐 API 客户端：搜索、取播放链接、下载、时长探测与转码。

搜索和取链走聚合接口（默认 GD Studio，netease 源），CDN 下载不经过它。
网易云音乐官方接口在本机被反爬挡掉（weapi 返回空），所以不直连。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import httpx


class MusicApiError(RuntimeError):
    """接口调用失败，message 面向用户，可直接发到群里。"""


def _as_json(response: httpx.Response):
    """解析接口响应；不说话的失败（超时/非 JSON）统一抛 MusicApiError。"""
    try:
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise MusicApiError("音乐接口没响应，等会儿再试。") from exc


async def search_songs(
    client: httpx.AsyncClient,
    *,
    api_base: str,
    keyword: str,
    source: str,
    count: int,
) -> list[dict]:
    """搜歌，返回候选列表（name/artist/...）；接口报错时抛 MusicApiError。"""
    response = await client.get(
        api_base,
        params={
            "types": "search",
            "source": source,
            "name": keyword,
            "count": count,
            "pages": 1,
        },
    )
    data = _as_json(response)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and item.get("id")]
    if isinstance(data, dict) and data.get("detail"):
        raise MusicApiError(f"搜索接口不支持这个来源（{data['detail']}）")
    return []


async def fetch_song_url(
    client: httpx.AsyncClient,
    *,
    api_base: str,
    source: str,
    song_id: str,
    bitrate: int,
) -> dict:
    """取一首歌的直链；拿不到（比如要会员）返回空 dict。"""
    response = await client.get(
        api_base,
        params={"types": "url", "source": source, "id": song_id, "br": bitrate},
    )
    data = _as_json(response)
    if isinstance(data, dict) and data.get("url"):
        return data
    return {}


async def download_to(
    client: httpx.AsyncClient,
    *,
    url: str,
    dest: Path,
    max_bytes: int,
    timeout: float,
) -> None:
    """流式下载到 dest；超过 max_bytes 中途放弃并删掉半成品。"""
    downloaded = 0
    try:
        async with client.stream("GET", url, timeout=timeout) as response:
            response.raise_for_status()
            with dest.open("wb") as file:
                async for chunk in response.aiter_bytes(64 * 1024):
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise MusicApiError(f"文件超过 {max_bytes // (1024 * 1024)}MB")
                    file.write(chunk)
    except MusicApiError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise MusicApiError("下载失败了，等会儿再试。") from exc
    if downloaded == 0:
        dest.unlink(missing_ok=True)
        raise MusicApiError("下载下来是空的，换首吧。")


# ---------- 选歌 ----------


def _norm(text: str) -> str:
    return re.sub(r"[\s　]+", "", str(text or "")).casefold()


def song_score(item: dict, query: str, *, index: int = 0) -> float:
    """单条候选和输入的匹配分；index 是接口排序里的位置，做平局兜底。"""
    needle = _norm(query)
    name = _norm(item.get("name"))
    artists = _norm(" ".join(str(a) for a in item.get("artist") or []))
    score = float(max(0, 4 - index))
    if name == needle:
        score += 100
    elif needle.startswith(name) or name.startswith(needle):
        score += 60
    elif name in needle or needle in name:
        score += 30
    # 用户特意写了歌手名（比如「晴天 周杰伦」），候选对上就加分
    for token in re.split(r"[^\w一-鿿]+", query):
        if _norm(token) and _norm(token) in artists:
            score += 10
    return score


def pick_song(candidates: list[dict], query: str) -> dict | None:
    """从候选里挑和输入最像的一首；打不过封面版的就用接口排序兜底。"""
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: song_score(item, query, index=candidates.index(item)),
    )


def song_label(song: dict) -> str:
    """给人看的一句话歌名：《name》 - artist。"""
    artists = "、".join(str(a) for a in song.get("artist") or [])
    name = str(song.get("name") or "未知歌曲")
    return f"《{name}》 - {artists}" if artists else f"《{name}》"


# ---------- 音频处理（ffmpeg 在本机，同步跑，调用方丢线程里） ----------


def probe_duration(path: Path) -> float | None:
    """用 ffmpeg 探时长（秒）；探测不了返回 None，不当错误处理。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        return None
    hours, minutes, seconds = (float(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def ensure_mp3(source: Path, target: Path, *, trim_seconds: float | None = None) -> Path:
    """统一转成 mp3；要截断时用 -t。转不了就原样返回，交给 NapCat 自己处理。"""
    if source.suffix.casefold() == ".mp3" and trim_seconds is None:
        return source
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return source
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
    ]
    if trim_seconds:
        command += ["-t", f"{trim_seconds:.1f}"]
    command += [
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(target),
    ]
    subprocess.run(command, check=True, timeout=300)
    return target
