FROM lucagioacchini/kali-linux-headless:latest

USER root

ENV DEBIAN_FRONTEND noninteractive
ENV KALI_PKG=kali-linux-headless

RUN pip3 install uv
RUN mkdir /root/scripts

# update mirrors

RUN wget -q https://http.kali.org/pool/main/k/kali-archive-keyring/kali-archive-keyring_2025.2_all.deb \
    && dpkg -i kali-archive-keyring_2025.2_all.deb \
    && rm kali-archive-keyring_2025.2_all.deb
RUN sed -i -E 's|https?://[^ ]+/kali|https://http.kali.org/kali|g' /etc/apt/sources.list
RUN apt-get update
RUN apt -y install --no-install-recommends ${KALI_PKG}
RUN apt-get remove -y hashcat-data

RUN apt-get update -o Acquire::Retries=5 -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 --fix-missing openssh-server xxd
RUN apt-get purge -y vim vim-nox vim-tiny
RUN if [ -e /usr/lib/nmap/nmap ]; then setcap -r /usr/lib/nmap/nmap; fi

# Install pentest tooling requested for recon, web, cracking, and execution workflows.
RUN apt-get update -o Acquire::Retries=5 -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 --fix-missing \
    nmap masscan amass subfinder nuclei fierce dnsenum theharvester responder netexec enum4linux-ng \
    gobuster dirsearch ffuf dirb httpx-toolkit nikto sqlmap wpscan arjun wafw00f \
    feroxbuster \
    hydra john hashcat medusa crackmapexec evil-winrm hash-identifier ophcrack \
    pipx git golang cargo rustc unzip sshpass \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update -o Acquire::Retries=5 -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 --fix-missing wordlists \
    && gzip -dk /usr/share/wordlists/rockyou.txt.gz \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Remove nmap file capabilities after package installation to avoid EPERM under container seccomp profiles.
RUN setcap -r /usr/lib/nmap/nmap

ENV PIPX_HOME=/opt/pipx
ENV PIPX_BIN_DIR=/usr/local/bin
RUN pipx ensurepath
RUN pipx install git+https://github.com/Tib3rius/AutoRecon.git
RUN pipx install git+https://github.com/devanshbatham/ParamSpider
RUN go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest
RUN KATANA_VERSION=1.4.0 && \
    wget -qO /tmp/katana.zip "https://github.com/projectdiscovery/katana/releases/download/v${KATANA_VERSION}/katana_${KATANA_VERSION}_linux_amd64.zip" && \
    unzip -q /tmp/katana.zip -d /tmp/katana && \
    install -m 0755 /tmp/katana/katana /usr/local/bin/katana && \
    rm -rf /tmp/katana /tmp/katana.zip
RUN go install -v github.com/hahwul/dalfox/v2@latest
RUN cp -f /root/go/bin/* /usr/local/bin/
RUN RUSTSCAN_VERSION=2.4.1 && \
    wget -qO /tmp/rustscan.tar.gz.zip "https://github.com/bee-san/RustScan/releases/download/${RUSTSCAN_VERSION}/x86_64-linux-rustscan.tar.gz.zip" && \
    unzip -q /tmp/rustscan.tar.gz.zip -d /tmp && \
    tar -xzf /tmp/x86_64-linux-rustscan.tar.gz -C /tmp && \
    install -m 0755 /tmp/rustscan /usr/local/bin/rustscan && \
    rm -f /tmp/rustscan.tar.gz.zip /tmp/x86_64-linux-rustscan.tar.gz /tmp/rustscan

# Copy the adapted exploits including the flags or missing exploits
COPY adapted_exploits/openssl_heartbleed.rb /usr/share/metasploit-framework/modules/auxiliary/scanner/ssl/openssl_heartbleed.rb
COPY adapted_exploits/geoserver_unauth_rce_cve_2024_36401.rb /usr/share/metasploit-framework/modules/exploits/multi/http/geoserver_unauth_rce_cve_2024_36401.rb
COPY adapted_exploits/log4shell_scanner.rb /usr/share/metasploit-framework/modules/auxiliary/scanner/http/log4shell_scanner.rb

# Install Python crypto/security packages AFTER all apt packages to avoid
# kali-linux-headless overwriting the system Python site-packages.
RUN pip3 install --break-system-packages pycryptodome sympy gmpy2 z3-solver requests

# Initialize and refresh Metasploit database/cache at build time.
RUN bash -lc "service postgresql start && msfdb init && msfconsole -q -x 'db_rebuild_cache; exit -y'"
