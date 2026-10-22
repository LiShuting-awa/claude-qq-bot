def split_at_boundaries(
    text: str,
    limit: int,
    *,
    minimum_limit: int,
    sentence_marks: tuple[str, ...],
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    limit = max(minimum_limit, int(limit))

    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            sentence = max((window.rfind(mark) for mark in sentence_marks), default=-1)
            if sentence >= limit // 2:
                cut = sentence + 1
        if cut < limit // 2:
            cut = limit

        chunk = rest[:cut].rstrip()
        if not chunk:
            cut = limit
            chunk = rest[:cut]
        chunks.append(chunk)
        rest = rest[cut:].lstrip("\n")

    if rest:
        chunks.append(rest.rstrip())

    return chunks
