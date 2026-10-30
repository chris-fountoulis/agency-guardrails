"""Build credential-shaped test strings at runtime.

Nothing in the repository is a literal credential: every value is
assembled from pieces with a seeded generator, so secret scanners that
read this repo have nothing to flag.
"""

import random
import string

ALNUM = string.ascii_letters + string.digits
UPPER_NUM = string.ascii_uppercase + string.digits


def _rand(n, alphabet=ALNUM, seed=7):
    rng = random.Random(seed * 1000 + n)
    return "".join(rng.choice(alphabet) for _ in range(n))


def anthropic():
    return "sk-" + "ant-" + "api03-" + _rand(48, ALNUM + "-_")


def openai():
    return "sk-" + "proj-" + _rand(48)


def github():
    return "gh" + "p_" + _rand(36)


def github_pat():
    return "github" + "_pat_" + _rand(30, ALNUM + "_")


def aws_id():
    return "AK" + "IA" + _rand(16, UPPER_NUM)


def aws_secret():
    return _rand(40, ALNUM + "/+")


def stripe():
    return "sk" + "_live_" + _rand(24)


def slack():
    return "xo" + "xb-" + _rand(12, string.digits) + "-" + _rand(24)


def slack_webhook():
    return "https://hooks." + "slack.com/services/" + "T" + _rand(8, UPPER_NUM) + "/B" + _rand(8, UPPER_NUM) + "/" + _rand(24)


def google():
    return "AI" + "za" + _rand(35, ALNUM + "_-")


def private_key():
    head = "-----" + "BEGIN " + "RSA PRIVATE" + " KEY-----"
    tail = "-----" + "END " + "RSA PRIVATE" + " KEY-----"
    body = "\n".join(_rand(64, ALNUM + "+/", seed=i) for i in range(3))
    return head + "\n" + body + "\n" + tail


def random_value(n=32):
    return _rand(n, ALNUM, seed=3)
