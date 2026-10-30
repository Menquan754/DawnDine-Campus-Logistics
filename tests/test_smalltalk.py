"""寒暄与自我介绍快速回复测试。"""

from __future__ import annotations

from dawndine.services.smalltalk import (
    CAPABILITY_REPLY,
    THANKS_REPLY,
    WELCOME_REPLY,
    small_talk_reply,
)


def test_greeting_returns_self_introduction() -> None:
    assert small_talk_reply("你好") == WELCOME_REPLY
    assert small_talk_reply("您好！") == WELCOME_REPLY
    assert small_talk_reply("hello") == WELCOME_REPLY


def test_identity_and_capability_questions() -> None:
    assert small_talk_reply("你是谁？") == CAPABILITY_REPLY
    assert small_talk_reply("你能做什么") == CAPABILITY_REPLY
    assert small_talk_reply("怎么用") == CAPABILITY_REPLY


def test_thanks_reply() -> None:
    assert small_talk_reply("谢谢") == THANKS_REPLY


def test_business_request_is_not_intercepted() -> None:
    assert small_talk_reply("你好，帮我生成今天的日管控台账") is None
    assert small_talk_reply("验收冷鲜猪肉，配送单 0—4℃，我实测 6℃") is None
