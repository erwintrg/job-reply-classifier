import pytest

from job_reply_classifier.prefilter import PreFilter

from .conftest import envelope

pre = PreFilter()


@pytest.mark.parametrize(
    "sender, subject",
    [
        ("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "Your job alert for automation engineer: 12 new positions"),
        ("LinkedIn <jobs-noreply@linkedin.com>", "New role match: Automation Engineer"),
        ("Indeed <donotreply@match.indeed.com>", "15 new jobs for you"),
        ("StepStone Jobagent <jobagent@stepstone.de>", "Neue Stelle für Sie: Automation Engineer (m/w/d)"),
        ("Glassdoor <noreply@glassdoor.com>", "Bewerbung leicht gemacht: 8 neue Stellen"),
        ("Example Board <hello@board-example.com>", "Your weekly job alert"),
    ],
)
def test_job_alerts_are_noise(sender, subject):
    decision = pre.check(envelope(sender, subject))
    assert (decision.candidate, decision.reason) == (False, "job alert")


def test_noise_runs_before_application_words():
    # "Stelle" and "Bewerbung" would make these candidates if the noise check came second.
    for subject in ("Neue Stelle für Sie: Automation Engineer", "Bewerbung leicht gemacht: 8 neue Stellen"):
        assert not pre.check(envelope("StepStone Jobagent <jobagent@stepstone.de>", subject)).candidate


@pytest.mark.parametrize(
    "sender, subject",
    [
        ("The Workflow Example Weekly <workflowexample@substack.com>", "Issue #42: what hiring managers ask in an interview"),
        ("Sample Digest <news@beehiiv.com>", "Five application tips"),
        ("Example Corp <info@corp-example.com>", "Newsletter October: our new positions"),
    ],
)
def test_newsletters_are_noise_even_with_interview_words(sender, subject):
    decision = pre.check(envelope(sender, subject))
    assert (decision.candidate, decision.reason) == (False, "newsletter")


def test_recruiter_message_through_linkedin_is_not_noise():
    # Only the alert senders are noise; a recruiter writing through LinkedIn must get through.
    decision = pre.check(envelope("Priya via LinkedIn <inmail-hit-reply@linkedin.com>", "Interview for the Automation role"))
    assert decision.candidate
