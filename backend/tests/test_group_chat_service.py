from backend.services.group_chat_service import GroupChatService


def test_enqueue_and_drain_should_keep_fifo_order():
    service = GroupChatService()

    created = service.enqueue_user_message(
        session_id="s-001",
        user_text="大家一起聊聊这个需求实现方案，分别给我建议。",
    )
    drained = service.drain_requests(session_id="s-001")

    assert [x.request_id for x in drained] == [x.request_id for x in created]
    assert 3 <= len(created) <= 5


def test_enqueue_should_rotate_first_speaker_between_rounds():
    service = GroupChatService()

    round_one = service.enqueue_user_message(session_id="s-rotate", user_text="聊聊今天")
    round_two = service.enqueue_user_message(session_id="s-rotate", user_text="聊聊今天")

    assert round_one
    assert round_two
    assert round_one[0].speaker["speaker_id"] != round_two[0].speaker["speaker_id"]


def test_build_group_prompt_should_forbid_role_tag_in_plain_text():
    service = GroupChatService()
    speaker = service.members()[0]

    prompt = service.build_group_prompt(
        user_text="我们聊聊教育",
        speaker={
            "speaker_type": "agent",
            "speaker_id": speaker.speaker_id,
            "speaker_name": speaker.speaker_name,
            "speaker_title": speaker.speaker_title,
            "speaker_personality": speaker.speaker_personality,
        },
        style_hint="先共情再建议",
        queue_index=1,
        queue_total=3,
        prior_replies=[{"speaker_name": "周老师", "text": "我先抛个问题"}],
    )

    assert "不要在正文中输出任何角色标签" in prompt
    assert "请在回复首行使用格式" not in prompt
