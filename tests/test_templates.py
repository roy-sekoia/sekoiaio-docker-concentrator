"""
Regression tests for the rsyslog jinja templates used by generate_config.py.

Context: multiple customer FortiGate intakes stop forwarding logs
simultaneously under sustained load, with the container staying "Up".
Logs show GnuTLS/omfwd errors ("Error in the push function", "TCPSendBuf
error -2078") which indicate the local TCP connection to
intake.sekoia.io silently died (no RST received) while rsyslog kept the
socket "established". Without TCP keepalive enabled on the omfwd action,
a subsequent send() can block on that dead socket indefinitely, wedging
the ruleset's single output worker and stalling that intake's queue
until the container is manually restarted.
"""
import os

import pytest
from jinja2 import Environment, FileSystemLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ITEM = {
    "name": "techno1",
    "protocol": "tcp",
    "port": 20516,
    "intake_key": "0123456789ABCDEF",
    "endpoint": "intake.sekoia.io",
    "default_queue_size": 100000,
}


def render(template_name):
    env = Environment(loader=FileSystemLoader(ROOT))
    return env.get_template(template_name).render(ITEM, env=os.environ)


@pytest.mark.parametrize("template_name", ["template.j2", "template_tls.j2", "stats_template.j2"])
def test_omfwd_action_enables_tcp_keepalive(template_name):
    rendered = render(template_name)
    # Find the omfwd action block (the "on the wire" output to Sekoia).
    assert 'type="omfwd"' in rendered
    action_block = rendered.split('type="omfwd"', 1)[1]
    assert 'KeepAlive="on"' in action_block, (
        f"{template_name}: omfwd action is missing KeepAlive=\"on\". Without TCP "
        "keepalive, a silently-dead connection to the intake endpoint can block "
        "the output worker forever instead of being detected and retried, "
        "stalling that intake until the container is restarted."
    )
