FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/ml-trainer

COPY requirements.txt ./
# NumPy 2.4+ wheels require x86-64-v2, which the beta VPS does not expose.
RUN python -m pip install --no-cache-dir -r requirements.txt numpy==2.3.5 \
    && useradd --uid 10001 --no-create-home appuser \
    && install -d -o appuser -g appuser data

COPY app/ app/
COPY web/ web/
COPY content/questions.json content/question-versions-v1.json content/
COPY Dockerfile ./

ARG MOCKROOM_SOURCE_COMMIT=
ARG MOCKROOM_SOURCE_DIRTY=
RUN python -m app.core.build_info --write --commit "$MOCKROOM_SOURCE_COMMIT" --dirty "$MOCKROOM_SOURCE_DIRTY"

USER appuser
CMD ["python", "-m", "app.server"]
