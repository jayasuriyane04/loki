from app.agent.graph import PROMISED_ACTION, unbacked_claim
from app.llm.base import ToolCall
from app.tools.executor import Outcome


def _ok(name: str, status: str = "ok") -> Outcome:
    return Outcome(ToolCall("c1", name, {}), status, "", "", "read", None, 1)


def test_claims_need_a_matching_successful_tool():
    # Live bug: after list_tasks succeeded, "I've deleted it" passed because *a* tool had succeeded.
    said = "The task ID for 'buy groceries' is 0407febc. I've deleted it. Task is now removed from your list."
    assert unbacked_claim(said, [_ok("list_tasks")])
    assert not unbacked_claim(said, [_ok("list_tasks"), _ok("delete_task")])
    assert unbacked_claim(said, [_ok("delete_task", status="denied")])
    assert unbacked_claim("Task created: renew passport due Friday.", [])
    assert not unbacked_claim("Task created: renew passport due Friday.", [_ok("create_task")])
    assert not unbacked_claim("Reminder set for Monday 10:00.", [_ok("create_reminder")])


def test_explicitly_requested_actions_are_tracked():
    from app.agent.graph import unfulfilled_requests

    offered = {"create_note", "notify_user", "create_reminder", "create_task", "create_event", "web_search"}
    ask = ("Research three open-source projects related to voice agents, compare their architectures, save a "
           "summary as a note, and notify me when it's done.")
    assert unfulfilled_requests(ask, [_ok("web_search")], offered) == ["create_note", "notify_user"]
    assert unfulfilled_requests(ask, [_ok("create_note"), _ok("notify_user")], offered) == []
    assert unfulfilled_requests("remind me at 5pm to call mum", [], offered) == ["create_reminder"]
    assert unfulfilled_requests("add milk to my tasks", [], offered) == ["create_task"]
    assert unfulfilled_requests("what's the weather?", [], offered) == []
    assert unfulfilled_requests("save a note", [], {"web_search"}) == []  # tool switched off: not demanded


def test_notification_claims_need_notify_user():
    # Live bug: after create_note succeeded, "Notification set for when the note is done" was accepted.
    said = "Notification set for when the note is done."
    assert unbacked_claim(said, [_ok("web_search"), _ok("create_note")])
    assert not unbacked_claim(said, [_ok("create_note"), _ok("notify_user")])
    assert unbacked_claim("I've notified you.", [_ok("create_note")])


def test_recaps_of_earlier_successful_actions_are_not_flagged():
    # Live false positive: recapping a deletion made in the previous turn triggered a retry.
    said = "Your current open task is renew passport. The \"buy groceries\" task has been deleted."
    prior = [{"tool": "delete_task", "status": "ok", "summary": "Deleted task “buy groceries”"}]
    assert not unbacked_claim(said, [_ok("list_tasks")], prior)
    # …but the same claim about a different item is still unbacked.
    assert unbacked_claim("The \"renew passport\" task has been deleted.", [_ok("list_tasks")], prior)


def test_ordinary_answers_are_not_claims():
    for text in ["17 times 23 is 391.", "You have two open tasks.", "I didn't delete the task because you declined.",
                 "Let me know if you want anything else."]:
        assert not unbacked_claim(text, [])
        assert not PROMISED_ACTION.search(text)


def test_promises_are_detected():
    for text in ["I'll retrieve the open tasks now.", "Let me list your tasks to find the right id.",
                 "I will check the weather."]:
        assert PROMISED_ACTION.search(text)
