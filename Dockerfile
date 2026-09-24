FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    rsyslog \
    rsyslog-gnutls \
    rsyslog-relp \
    gettext-base \
    python3 \
    python3-yaml \
    python3-jinja2 \
    wget

RUN wget -O /SEKOIA-IO-intake.pem https://app.sekoia.io/assets/files/SEKOIA-IO-intake.pem

# Setting default environement variables
ENV DISK_SPACE=32g
ENV MEMORY_MESSAGES=100000
ENV REGION=FRA1

# Setting up Rsyslog
RUN rm -rf /etc/rsyslog.d/50-default.conf

COPY generate_config.py generate_config.py
COPY healthcheck.py /healthcheck.py
COPY rsyslog-imstats /etc/logrotate.d/rsyslog-imstats
COPY rsyslog.conf rsyslog.conf
COPY entrypoint.sh entrypoint.sh
COPY intakes.yaml intakes.yaml
COPY template.j2 template.j2
COPY template_tls.j2 template_tls.j2
COPY stats_template.j2 stats_template.j2

RUN chmod +x entrypoint.sh

# Some intakes' output actions can get stuck (e.g. a GnuTLS/omfwd worker
# thread hang) while rsyslogd keeps running, silently stopping log
# forwarding until the container is manually restarted. This healthcheck
# detects such a stall from impstats and restarts rsyslogd automatically so
# `restart: always` can bring the container back to a healthy state.
HEALTHCHECK --interval=90s --timeout=10s --start-period=5m --retries=1 \
    CMD python3 /healthcheck.py

ENTRYPOINT ["/entrypoint.sh"]
CMD ["rsyslogd", "-n"]
