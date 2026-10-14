# jpetstore를 "고객 레거시 WAS"로 재현한다: Tomcat 9 + 외부 PostgreSQL + OTel Java Agent(코드 수정 없이 부착).
# 빌드 컨텍스트는 저장소 루트(automcp/)다.

FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY targets/jpetstore-6/ .
COPY spike/jpetstore/applicationContext.xml src/main/webapp/WEB-INF/applicationContext.xml
RUN mvn -B -q -DskipTests -Denforcer.skip=true -Dlicense.skip=true -Dformatter.skip=true -Dimpsort.skip=true -Dcheckstyle.skip=true -Dspotbugs.skip=true -Dpmd.skip=true -Dmodernizer.skip=true package

FROM tomcat:9.0-jdk17-temurin
# 운영 WAS에 JDBC 드라이버를 공용 lib로 두는 전형적인 레거시 배치
ADD https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar /usr/local/tomcat/lib/
# 캡처 키트: 개발/스테이징 WAS에 JVM 옵션 한 줄로 부착하는 OTel 에이전트
ADD https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.31.1/opentelemetry-javaagent.jar /otel/opentelemetry-javaagent.jar
COPY --from=build /src/target/jpetstore.war /usr/local/tomcat/webapps/jpetstore.war
