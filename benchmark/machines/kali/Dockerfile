FROM lucagioacchini/kali-linux-headless:latest

USER root

ENV DEBIAN_FRONTEND noninteractive
ENV KALI_PKG=kali-linux-headless

RUN pip3 install pycryptodome
RUN mkdir /root/scripts

# update mirrors

RUN wget -q https://http.kali.org/pool/main/k/kali-archive-keyring/kali-archive-keyring_2025.1_all.deb \
    && dpkg -i kali-archive-keyring_2025.1_all.deb \
    && rm kali-archive-keyring_2025.1_all.deb
RUN sed -i -E 's|https?://[^ ]+/kali|https://http.kali.org/kali|g' /etc/apt/sources.list
RUN apt-get update
RUN apt -y install --no-install-recommends ${KALI_PKG}
RUN apt-get remove -y hashcat-data || true

RUN apt-get update -o Acquire::Retries=5 -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 --fix-missing openssh-server xxd
RUN apt-get purge -y vim vim-nox vim-tiny || true
RUN if [ -e /usr/lib/nmap/nmap ]; then setcap -r /usr/lib/nmap/nmap || true; fi

# Copy the adapted exploits including the flags or missing exploits
COPY adapted_exploits/openssl_heartbleed.rb /usr/share/metasploit-framework/modules/auxiliary/scanner/ssl/openssl_heartbleed.rb
COPY adapted_exploits/geoserver_unauth_rce_cve_2024_36401.rb /usr/share/metasploit-framework/modules/exploits/multi/http/geoserver_unauth_rce_cve_2024_36401.rb
COPY adapted_exploits/log4shell_scanner.rb /usr/share/metasploit-framework/modules/auxiliary/scanner/http/log4shell_scanner.rb
