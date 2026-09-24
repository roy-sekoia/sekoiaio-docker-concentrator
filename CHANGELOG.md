# Changelog

All notable changes with sekoiaio concentrator will be documented in this file.

## [2.7.6]

- Enable TCP `KeepAlive` on the `omfwd` actions (and `tcp.keepalive` on the
  `omrelp` actions) used to send logs to Sekoia intakes. Under sustained load,
  the local TCP connection to an intake endpoint can silently die (no RST
  received) while rsyslog still considers it "established"; without keepalive,
  a subsequent write can block indefinitely on that dead socket, wedging the
  ruleset's single output worker and stalling that intake until the container
  is manually restarted. Keepalive lets the kernel detect the dead peer and
  fail the write, so rsyslog's existing `action.resumeRetryCount="-1"` retry
  logic can reconnect.
- Add a self-healing healthcheck (`healthcheck.py`) as defense-in-depth: it
  detects when a per-intake output action is stuck (backlog present but
  nothing forwarded for several consecutive `impstats` intervals) for any
  other reason and automatically restarts `rsyslogd` so the `restart: always`
  policy can recover the container, instead of requiring a manual restart.
- Set an explicit `interval="60"` on the `impstats` module so the healthcheck can
  reliably observe fresh per-interval statistics.

## [2.7.5]

- Add `action.resumeRetryCount=-1` and `action.resumeInterval=30` to all output actions:
  - Fixes issue where rsyslog would suspend forwarding actions after network outages
  - Ensures queued logs are reliably resent when connectivity is restored
  - Prevents data loss during temporary network interruptions
  - Applies to TCP, RELP, and stats monitoring output actions in all templates (template.j2, template_tls.j2, stats_template.j2)

## [2.7.4]

- Update default regional intake endpoint

## [2.7.3]

- Customize destination endpoint

## [2.7.2]

- Reset counters for forwarder monitoring events
- Added the ability to define a custom queue size for an intake.
- Introduced the capability to send events to Sekoia using the RELP protocol.

## [2.7.1]

- Support USA1 region
- Fix TLS template

## [2.7.0]

- Enable forwarder monitoring

## [2.6.0]

- Add the support of TLS

## [2.5.1]

- Check the format of Intake keys.

## [2.5]

- Added the support of multi-region

## [2.4]

- Capacity to import a custom rsyslog configuration

## [2.3]

- Improve performances for multiple ruleset configuration (ref: https://www.rsyslog.com/doc/concepts/multi_ruleset.html#rulesets-and-queues)

## [2.2]

- Update main queue settings

## [2.1]

- Add local timestamp in rsyslog header instead of received timestamp 

## [2.0]

- Manage syslog RFC 3164 (only 5424 in 1.0 version)
- Add advanced debug options
- Update implementation from bash to jinja

## [1.0] 

- Initial version
