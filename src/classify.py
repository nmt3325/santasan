import re
from dataclasses import dataclass, field

FOLLOW_PATTERNS = [
    r"フォロー",
    r"follow",
    r"フォロワー",
]

REPOST_PATTERNS = [
    r"\bRT\b",
    r"リポスト",
    r"リツイート",
    r"拡散",
    r"retweet",
    r"repost",
]

LIKE_PATTERNS = [
    r"いいね",
    r"♥",
    r"❤",
    r"ハート",
    r"like",
    r"お気に入り",
]

REPLY_PATTERNS = [
    r"リプライ",
    r"コメント",
    r"返信",
    r"reply",
    r"感想",
    r"理由",
]

SWEEPSTAKES_SIGNALS = [
    r"懸賞",
    r"プレゼント",
    r"キャンペーン",
    r"当選",
    r"抽選",
    r"プレゼントキャンペーン",
    r"配布",
    r"無料",
    r"ギフト",
    r"当たる",
]

HASHTAG_RE = re.compile(r"#([^\s#]+)")


def _match_any(text: str, patterns: list[str]) -> bool:
    lower = text.lower()
    return any(re.search(p, lower, re.IGNORECASE) for p in patterns)


@dataclass
class EntryRequirements:
    follow: bool = False
    repost: bool = False
    like: bool = False
    reply: bool = False
    hashtags: list[str] = field(default_factory=list)
    reply_hint: str = ""
    is_sweepstakes: bool = False


def classify(tweet_text: str) -> EntryRequirements:
    req = EntryRequirements()
    req.is_sweepstakes = _match_any(tweet_text, SWEEPSTAKES_SIGNALS)
    req.follow = _match_any(tweet_text, FOLLOW_PATTERNS)
    req.repost = _match_any(tweet_text, REPOST_PATTERNS)
    req.like = _match_any(tweet_text, LIKE_PATTERNS)
    req.reply = _match_any(tweet_text, REPLY_PATTERNS)
    req.hashtags = HASHTAG_RE.findall(tweet_text)

    if req.reply:
        m = re.search(r"(#\S+|「.+?」|【.+?】)", tweet_text)
        req.reply_hint = m.group(0) if m else ""

    return req
