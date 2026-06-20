import os
from stagehand import Stagehand

ENV_KEYS = ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "MODEL_API_KEY")


def main():
    print(all(os.environ.get(k) for k in ENV_KEYS))

    client = Stagehand()
    session_id = None
    try:
        resp = client.sessions.start(model_name="anthropic/claude-sonnet-4-6")
        session_id = resp.data.session_id
        print(f"session_id: {session_id}")
        print(f"https://browserbase.com/sessions/{session_id}")

        client.sessions.navigate(id=session_id, url="https://news.ycombinator.com")
        result = client.sessions.extract(
            id=session_id,
            instruction="extract the title and points of the top story",
        )
        print(result)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
    finally:
        if session_id:
            client.sessions.end(id=session_id)


if __name__ == "__main__":
    main()
