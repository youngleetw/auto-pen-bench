FROM openjdk:17.0.2-slim

RUN set -ex \
    && apt-get update -o Acquire::Retries=5 -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 --fix-missing curl unzip ca-certificates \
    && curl -#SL https://sourceforge.net/projects/geoserver/files/GeoServer/2.23.2/geoserver-2.23.2-bin.zip/download -o /tmp/geoserver.zip \
    && mkdir /mnt/geoserver \
    && unzip /tmp/geoserver.zip -d /mnt/geoserver

EXPOSE 8080
WORKDIR /mnt/geoserver

ENV JAVA_OPTS="-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5005"
CMD [ "/mnt/geoserver/bin/startup.sh" ]

USER root

COPY flag.txt /root/flag.txt
