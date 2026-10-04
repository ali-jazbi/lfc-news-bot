"""Split Telegram HTML without truncation or breaking entities/formatting."""
import re
from html.parser import HTMLParser


def split_html(text, limit=3500):
    class Splitter(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.parts, self.stack, self.current = [], [], ''

        def flush(self):
            if self.current:
                self.parts.append(self.current + ''.join('</' + tag + '>' for tag, _ in reversed(self.stack)))
                self.current = ''.join(raw for _, raw in self.stack)

        def append(self, token):
            closers = sum(len(tag) + 3 for tag, _ in self.stack)
            if len((self.current + token).encode('utf-16-le')) // 2 + closers > limit:
                self.flush()
            self.current += token

        def handle_starttag(self, tag, attrs):
            raw = self.get_starttag_text()
            self.append(raw)
            self.stack.append((tag, raw))

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1][0] == tag:
                self.append('</' + tag + '>')
                self.stack.pop()

        def handle_data(self, data):
            for token in re.findall(r'\s+|[^\s]+', data):
                if len(token.encode('utf-16-le')) // 2 > limit // 2:
                    for ch in token:
                        self.append(ch)
                else:
                    self.append(token)

        def handle_entityref(self, name):
            self.append('&' + name + ';')

        def handle_charref(self, name):
            self.append('&#' + name + ';')

    parser = Splitter()
    parser.feed(text)
    parser.close()
    parser.flush()
    return parser.parts or ['•']
