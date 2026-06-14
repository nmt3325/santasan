import asyncio
import logging
import os
import random
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

_ORGANIC_TOPICS = [
    "今日の天気や季節の変化",
    "最近食べた食事やカフェ",
    "趣味や読書について",
    "散歩や外出の感想",
    "音楽や映画の感想",
    "家でのリラックスタイム",
    "仕事や勉強の合間の一息",
    "空や自然の景色",
    "最近買ったもの",
    "今日の小さな発見",
]

def _build_organic_prompt() -> str:
    topic = random.choice(_ORGANIC_TOPICS)
    return f"""以下の条件でツイートを1件だけ出力してください。
- テーマ: {topic}
- 日本語の日常的な話題
- 50〜120文字
- ハッシュタグ1〜2個、絵文字1〜2個
- 番号・箇条書き・説明・前置き一切なし
- ツイート本文のみ1行で出力"""

REPLY_PROMPT_TEMPLATE = """以下の懸賞ツイートへの返信を1件だけ出力してください。
- 日本語、50〜100文字
- 応募への期待・関心を自然に表現
- ハッシュタグが指定されていれば末尾に含める: {hashtags}
- 番号・箇条書き・説明・「返信案」などの前置き一切なし
- 返信本文のみ1行で出力

懸賞ツイート:
{tweet_text}"""

FALLBACK_ORGANIC_TWEETS = [
    "今日もいい天気ですね☀️ 散歩日和！ #日常",
    "コーヒーを飲みながら一息つく時間が好きです☕ #まったり",
    "最近読んだ本がとても面白かった📚 おすすめです！",
    "夕飯何にしようか迷い中🍽️ #悩み",
    "今日は早起きできました！気持ちいい朝です🌅 #早起き",
]


async def _call_node(prompt: str, node_script: str, timeout: float) -> str:
    script_path = PROJECT_ROOT / node_script
    if not script_path.exists():
        raise FileNotFoundError(f"Node script not found: {script_path}")

    proc = await asyncio.create_subprocess_exec(
        "node", str(script_path), prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(script_path.parent),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"rakutenai generator timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(f"rakutenai generator error: {stderr.decode()}")

    return stdout.decode().strip()


async def generate_organic_tweet(node_script: str = "generator_node/generate.mjs", timeout: float = 30.0) -> str:
    try:
        prompt = _build_organic_prompt()
        text = await _call_node(prompt, node_script, timeout)
        logger.debug("Generated organic tweet: %r", text)
        return text
    except Exception as e:
        logger.warning("rakutenai unavailable (%s), using fallback tweet", e)
        return random.choice(FALLBACK_ORGANIC_TWEETS)


async def generate_reply(
    tweet_text: str,
    hashtags: list[str] | None = None,
    node_script: str = "generator_node/generate.mjs",
    timeout: float = 30.0,
) -> str:
    tags_str = " ".join(f"#{t}" for t in (hashtags or []))
    prompt = REPLY_PROMPT_TEMPLATE.format(tweet_text=tweet_text, hashtags=tags_str)
    try:
        text = await _call_node(prompt, node_script, timeout)
        logger.debug("Generated reply: %r", text)
        return text
    except Exception as e:
        logger.warning("rakutenai unavailable (%s), using fallback reply", e)
        return f"応募します！よろしくお願いします🙏 {tags_str}".strip()
