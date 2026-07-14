"""
test_brain.py — Test the AI brain without any real credentials.
Run: python test_brain.py
"""

import os
import sys
import json
sys.path.insert(0, os.path.dirname(__file__))

# Set a dummy key for testing
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("MY_NAME", "Rahul Sharma")
os.environ.setdefault("MY_PROFESSION", "Digital Creator & Entrepreneur")
os.environ.setdefault("MY_TONE", "friendly, direct, professional")

# ── Simulate messages without calling real APIs ────────────────────────────────

TEST_MESSAGES = [
    {
        "platform": "instagram",
        "sender": "Sarah Johnson",
        "message": "Hey! Loved your last post about productivity. Would love to collab on a YouTube video with you. My channel has 120k subs. Let me know!",
        "expected_intent": "collab_request",
    },
    {
        "platform": "instagram",
        "sender": "unknown_user_xyz",
        "message": "Click here to get 10000 followers FREE http://spam.xyz/followers amazing deal",
        "expected_intent": "spam",
    },
    {
        "platform": "gmail",
        "sender": "client@company.com",
        "message": "Subject: Urgent - Project deadline\n\nHi, we need to discuss the project timeline. Can we jump on a call today? This is quite urgent.",
        "expected_intent": "customer_support",
    },
    {
        "platform": "whatsapp",
        "sender": "+91 98765 43210",
        "message": "Bhai, tumhara course kitne ka hai? Kya discount milega?",
        "expected_intent": "pricing_query",
    },
    {
        "platform": "twitter",
        "sender": "techfan_india (@techfan_india)",
        "message": "@rahulsharma Your tutorial on Python agents was incredible! Learned so much. Thank you for sharing this!",
        "expected_intent": "compliment",
    },
]


def run_tests():
    print("\n" + "="*60)
    print("  BRAIN TEST — Testing intent detection & reply generation")
    print("="*60)

    try:
        from agents.brain import process_message
    except Exception as e:
        print(f"Import error: {e}")
        return

    passed = 0
    failed = 0

    for i, test in enumerate(TEST_MESSAGES, 1):
        print(f"\n[Test {i}] {test['platform'].upper()} from {test['sender'][:30]}")
        print(f"  Message: \"{test['message'][:80]}...\"")
        print(f"  Expected intent: {test['expected_intent']}")

        try:
            result = process_message(
                sender_name=test["sender"],
                message=test["message"],
                platform=test["platform"],
            )

            if result.skip:
                print(f"  → SKIPPED: {result.skip_reason}")
                if test["expected_intent"] == "spam":
                    print("  ✓ PASS (correctly identified as spam)")
                    passed += 1
                else:
                    print(f"  ? (skipped but expected {test['expected_intent']})")
            else:
                actual_intent = result.intent.intent
                match = "✓ PASS" if actual_intent == test["expected_intent"] else "~ CLOSE"
                print(f"  → Intent:   {actual_intent} [{match}]")
                print(f"  → Urgency:  {result.intent.urgency}")
                print(f"  → Language: {result.intent.language}")
                print(f"  → Key ask:  {result.intent.key_ask}")
                print(f"  → Reply:    \"{result.reply_text[:120]}...\"")
                passed += 1

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed out of {len(TEST_MESSAGES)} tests")
    print("="*60)


if __name__ == "__main__":
    # Check API key
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key or key == "test-key" or key.startswith("sk-ant-"):
        if key == "test-key":
            print("\n⚠ No real ANTHROPIC_API_KEY set.")
            print("  Set it in .env then run: python test_brain.py")
            print("\n  Showing what the brain WOULD process:\n")
            for t in TEST_MESSAGES:
                print(f"  [{t['platform']}] {t['sender']}: \"{t['message'][:60]}...\"")
                print(f"    → Would detect: {t['expected_intent']}")
                print()
        else:
            run_tests()
    else:
        run_tests()
