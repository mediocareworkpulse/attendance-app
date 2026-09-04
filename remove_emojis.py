import os
import re

# Emoji Unicode ranges (common)
emoji_pattern = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa70-\U0001fa73"
    "\U0001fa78-\U0001fa7a"
    "\U0001fa80-\U0001fa82"
    "\U0001fa90-\U0001fa95"
    "\U0001fa00-\U0001fa53"
    "\U0001fae0-\U0001fae8"
    "\U0001faf0-\U0001faf6"
    "\U00002600-\U000027BF"  # misc symbols
    "\U0001F000-\U0001F02F"  # Mahjong
    "\U0001F0A0-\U0001F0FF"  # playing cards
    "\U0001F300-\U0001F5FF"  # symbols
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric shapes
    "\U0001F800-\U0001F8FF"  # supplemental arrows
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended
    "\U0000231A-\U0000231B"  # watch
    "\U000023E9-\U000023EC"  # media control
    "\U000023F0"             # alarm
    "\U000023F3"             # hourglass
    "\U000025AA-\U000025FE"  # geometric
    "\U00002B50"             # star
    "\U00002B55"             # circle
    "\U00002764"             # heart
    "\U00002705"             # check mark
    "\U00002753"             # question mark
    "\U00002754"             # white question
    "\U00002795"             # plus
    "\U00002796"             # minus
    "\U00002797"             # division
    "\U000027A1"             # arrow
    "\U000027B0"             # curly loop
    "\U000027BF"             # double curly loop
    "\U0001F1E6-\U0001F1FF"  # flags
    "]+",
    flags=re.UNICODE,
)

def remove_emojis_from_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        cleaned = emoji_pattern.sub("", content)
        # Also remove leading/trailing spaces left by emoji removal in text
        cleaned = re.sub(r"\s+", " ", cleaned)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(cleaned)
        print(f"Cleaned: {filepath}")
    except Exception as e:
        print(f"Error processing {filepath}: {e}")

def main():
    target_dirs = ["templates", "static"]
    for dir_path in target_dirs:
        if not os.path.isdir(dir_path):
            print(f"Directory {dir_path} not found, skipping.")
            continue
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                if file.endswith((".html", ".css", ".js")):
                    filepath = os.path.join(root, file)
                    remove_emojis_from_file(filepath)

if __name__ == "__main__":
    main()
