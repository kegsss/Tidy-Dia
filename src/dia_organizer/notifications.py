import subprocess


def notify(title: str, body: str) -> None:
    script = (
        f'display notification "{body.replace(chr(34), chr(39))}" '
        f'with title "{title.replace(chr(34), chr(39))}"'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)
