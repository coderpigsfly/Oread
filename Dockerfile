# Python version and Debian release are both pinned, so a rebuild months from
# now gets the same base. To move to a newer Python: change this line and the
# PYTHON line in tools/lock.sh, run tools/lock.sh, rebuild, run the tests.
FROM python:3.12-slim-trixie
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY oread/ oread/
COPY settings.yaml models.yaml device-types.yaml ./
COPY tests/audio/ tests/audio/
COPY sample/ sample/
COPY tools/trim_check.py tools/trim_check.py
COPY docs/user-guide.md docs/user-guide.md
EXPOSE 10310-10339
CMD ["python", "-m", "oread"]
