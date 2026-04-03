"""
highlighter.py  —  Syntax highlighting + basic error checking
Supports: Python, Java, JavaScript, Kotlin, HTML, CSS, Markdown
"""

import ast
import re
from PyQt5.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont
)
from PyQt5.QtCore import QRegularExpression, Qt


# ---------------------------------------------------------------------------
# Colour palette  (tweak these to change every language at once)
# ---------------------------------------------------------------------------
PALETTE = {
    "keyword":      "#C792EA",   # purple
    "keyword2":     "#82AAFF",   # soft blue  (secondary keywords / modifiers)
    "builtin":      "#FFCB6B",   # amber
    "string":       "#C3E88D",   # green
    "string2":      "#F78C6C",   # orange  (f-strings / template literals)
    "number":       "#F78C6C",   # orange
    "comment":      "#546E7A",   # muted blue-grey
    "function":     "#82AAFF",   # blue
    "class_name":   "#FFCB6B",   # amber
    "decorator":    "#C792EA",   # purple
    "operator":     "#89DDFF",   # cyan
    "type":         "#FFCB6B",   # amber
    "tag":          "#F07178",   # red  (HTML)
    "attr":         "#C792EA",   # purple (HTML attrs)
    "selector":     "#C792EA",   # CSS selectors
    "property":     "#82AAFF",   # CSS properties
    "md_heading":   "#C792EA",   # Markdown headings
    "md_bold":      "#FFCB6B",   # Markdown bold
    "md_italic":    "#C3E88D",   # Markdown italic
    "md_code":      "#F78C6C",   # Markdown inline code
    "md_link":      "#82AAFF",   # Markdown links
    "error":        "#FF5370",   # error underline
}


def _fmt(color_hex: str, bold=False, italic=False, underline=False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color_hex))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    if italic:
        fmt.setFontItalic(True)
    if underline:
        fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        fmt.setUnderlineColor(QColor(color_hex))
    return fmt


# ---------------------------------------------------------------------------
# Base highlighter — rule-based
# ---------------------------------------------------------------------------
class _BaseHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._ml_start: QRegularExpression | None = None
        self._ml_end:   QRegularExpression | None = None
        self._ml_fmt:   QTextCharFormat | None    = None
        self._build_rules()

    def _add(self, pattern: str, fmt: QTextCharFormat):
        self._rules.append((QRegularExpression(pattern), fmt))

    def _build_rules(self):
        """Override in subclasses."""
        pass

    def _set_multiline_comment(self, start: str, end: str):
        self._ml_start = QRegularExpression(re.escape(start))
        self._ml_end   = QRegularExpression(re.escape(end))
        self._ml_fmt   = _fmt(PALETTE["comment"], italic=True)

    def highlightBlock(self, text: str):
        # Single-line rules
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Multi-line comment / string blocks
        if self._ml_start:
            self._apply_multiline(text)

    # Block-state: 0 = normal, 1 = inside multi-line block
    def _apply_multiline(self, text: str):
        if self.previousBlockState() == 1:
            start_idx = 0
            add = 0
        else:
            m = self._ml_start.match(text)
            if not m.hasMatch():
                self.setCurrentBlockState(0)
                return
            start_idx = m.capturedStart()
            add = m.capturedLength()

        while start_idx >= 0:
            m = self._ml_end.match(text, start_idx + add)
            if not m.hasMatch():
                self.setCurrentBlockState(1)
                self.setFormat(start_idx, len(text) - start_idx, self._ml_fmt)
                return
            end = m.capturedStart() + m.capturedLength()
            self.setFormat(start_idx, end - start_idx, self._ml_fmt)
            m2 = self._ml_start.match(text, end)
            start_idx = m2.capturedStart() if m2.hasMatch() else -1
            add = m2.capturedLength() if m2.hasMatch() else 0

        self.setCurrentBlockState(0)


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
class PythonHighlighter(_BaseHighlighter):
    KEYWORDS = [
        "False","None","True","and","as","assert","async","await",
        "break","class","continue","def","del","elif","else","except",
        "finally","for","from","global","if","import","in","is",
        "lambda","nonlocal","not","or","pass","raise","return",
        "try","while","with","yield",
    ]
    BUILTINS = [
        "abs","all","any","bin","bool","breakpoint","bytearray","bytes",
        "callable","chr","classmethod","compile","complex","delattr","dict",
        "dir","divmod","enumerate","eval","exec","filter","float","format",
        "frozenset","getattr","globals","hasattr","hash","help","hex","id",
        "input","int","isinstance","issubclass","iter","len","list","locals",
        "map","max","memoryview","min","next","object","oct","open","ord",
        "pow","print","property","range","repr","reversed","round","set",
        "setattr","slice","sorted","staticmethod","str","sum","super",
        "tuple","type","vars","zip",
    ]

    def _build_rules(self):
        kw  = _fmt(PALETTE["keyword"],   bold=True)
        bi  = _fmt(PALETTE["builtin"])
        st  = _fmt(PALETTE["string"])
        st2 = _fmt(PALETTE["string2"])
        nm  = _fmt(PALETTE["number"])
        cm  = _fmt(PALETTE["comment"],   italic=True)
        fn  = _fmt(PALETTE["function"],  bold=True)
        cl  = _fmt(PALETTE["class_name"],bold=True)
        dc  = _fmt(PALETTE["decorator"])
        op  = _fmt(PALETTE["operator"])

        # keywords
        for kw_text in self.KEYWORDS:
            self._add(r'\b' + kw_text + r'\b', kw)
        # builtins
        for bi_text in self.BUILTINS:
            self._add(r'\b' + bi_text + r'\b', bi)

        # decorators  @something
        self._add(r'@\w+', dc)
        # function definitions
        self._add(r'\bdef\s+(\w+)', fn)
        # class definitions
        self._add(r'\bclass\s+(\w+)', cl)
        # f-strings (simple)
        self._add(r'\bf["\'].*?["\']', st2)
        # triple-quoted strings (single line portions only; multiline handled separately)
        self._add(r'""".*?"""', st)
        self._add(r"'''.*?'''", st)
        # regular strings
        self._add(r'"[^"\\]*(\\.[^"\\]*)*"', st)
        self._add(r"'[^'\\]*(\\.[^'\\]*)*'", st)
        # numbers
        self._add(r'\b[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?\b', nm)
        self._add(r'\b0x[0-9A-Fa-f]+\b', nm)
        # operators
        self._add(r'[+\-*/%=<>!&|^~]+', op)
        # single-line comment
        self._add(r'#[^\n]*', cm)

        # multi-line strings as block comments
        self._set_multiline_comment('"""', '"""')


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------
class JavaHighlighter(_BaseHighlighter):
    KEYWORDS = [
        "abstract","assert","boolean","break","byte","case","catch","char",
        "class","continue","default","do","double","else","enum","extends",
        "final","finally","float","for","goto","if","implements","import",
        "instanceof","int","interface","long","native","new","package",
        "private","protected","public","return","short","static","strictfp",
        "super","switch","synchronized","this","throw","throws","transient",
        "try","var","void","volatile","while","record","sealed","permits",
        "yield","null","true","false",
    ]
    TYPES = [
        "String","Integer","Long","Double","Float","Boolean","Character",
        "Byte","Short","Object","List","Map","Set","ArrayList","HashMap",
        "HashSet","Optional","Stream","Comparator","Exception","RuntimeException",
        "Thread","Runnable","Callable","Future","CompletableFuture",
    ]

    def _build_rules(self):
        kw = _fmt(PALETTE["keyword"],    bold=True)
        ty = _fmt(PALETTE["type"],       bold=False)
        st = _fmt(PALETTE["string"])
        ch = _fmt(PALETTE["string"])
        nm = _fmt(PALETTE["number"])
        cm = _fmt(PALETTE["comment"],    italic=True)
        fn = _fmt(PALETTE["function"],   bold=True)
        cl = _fmt(PALETTE["class_name"], bold=True)
        an = _fmt(PALETTE["decorator"])
        op = _fmt(PALETTE["operator"])

        for kw_text in self.KEYWORDS:
            self._add(r'\b' + kw_text + r'\b', kw)
        for ty_text in self.TYPES:
            self._add(r'\b' + ty_text + r'\b', ty)

        # annotations
        self._add(r'@\w+', an)
        # class declarations
        self._add(r'\bclass\s+(\w+)', cl)
        # method calls / declarations
        self._add(r'\b([A-Za-z_]\w*)\s*(?=\()', fn)
        # strings
        self._add(r'"[^"\\]*(\\.[^"\\]*)*"', st)
        # chars
        self._add(r"'[^'\\]*(\\.[^'\\]*)*'", ch)
        # numbers
        self._add(r'\b[0-9]+[lLfFdD]?\b', nm)
        self._add(r'\b0x[0-9A-Fa-f]+\b', nm)
        # operators
        self._add(r'[+\-*/%=<>!&|^~?:]+', op)
        # line comment
        self._add(r'//[^\n]*', cm)

        self._set_multiline_comment('/*', '*/')


# ---------------------------------------------------------------------------
# JavaScript / TypeScript
# ---------------------------------------------------------------------------
class JavaScriptHighlighter(_BaseHighlighter):
    KEYWORDS = [
        "break","case","catch","class","const","continue","debugger","default",
        "delete","do","else","export","extends","finally","for","function",
        "if","import","in","instanceof","let","new","of","return","static",
        "super","switch","this","throw","try","typeof","var","void","while",
        "with","yield","async","await","from","as","null","undefined",
        "true","false","=>",
    ]
    BUILTINS = [
        "console","window","document","Math","JSON","Promise","Array",
        "Object","String","Number","Boolean","Date","RegExp","Error",
        "Map","Set","WeakMap","WeakSet","Symbol","Proxy","Reflect",
        "fetch","setTimeout","setInterval","clearTimeout","clearInterval",
        "parseInt","parseFloat","isNaN","isFinite","encodeURIComponent",
        "decodeURIComponent","require","module","exports","process",
        "globalThis","structuredClone","queueMicrotask",
    ]

    def _build_rules(self):
        kw  = _fmt(PALETTE["keyword"],  bold=True)
        bi  = _fmt(PALETTE["builtin"])
        st  = _fmt(PALETTE["string"])
        tl  = _fmt(PALETTE["string2"])   # template literals
        nm  = _fmt(PALETTE["number"])
        cm  = _fmt(PALETTE["comment"],  italic=True)
        fn  = _fmt(PALETTE["function"], bold=True)
        cl  = _fmt(PALETTE["class_name"], bold=True)
        op  = _fmt(PALETTE["operator"])
        rx  = _fmt(PALETTE["string2"])   # regex literals

        for kw_text in self.KEYWORDS:
            self._add(r'\b' + kw_text + r'\b', kw)
        for bi_text in self.BUILTINS:
            self._add(r'\b' + bi_text + r'\b', bi)

        # class names
        self._add(r'\bclass\s+(\w+)', cl)
        # function/method names
        self._add(r'\b([A-Za-z_$]\w*)\s*(?=\()', fn)
        # template literals  `…`
        self._add(r'`[^`\\]*(\\.[^`\\]*)*`', tl)
        # strings
        self._add(r'"[^"\\]*(\\.[^"\\]*)*"', st)
        self._add(r"'[^'\\]*(\\.[^'\\]*)*'", st)
        # numbers
        self._add(r'\b[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?\b', nm)
        self._add(r'\b0x[0-9A-Fa-f]+\b', nm)
        # regex literals (simple heuristic)
        self._add(r'(?<![)\w])/(?!/)[^/\n]+/[gimsuy]*', rx)
        # operators
        self._add(r'[+\-*/%=<>!&|^~?:]+', op)
        # line comment
        self._add(r'//[^\n]*', cm)

        self._set_multiline_comment('/*', '*/')


# ---------------------------------------------------------------------------
# Kotlin
# ---------------------------------------------------------------------------
class KotlinHighlighter(_BaseHighlighter):
    KEYWORDS = [
        "as","break","class","continue","do","else","false","for","fun",
        "if","in","interface","is","null","object","package","return",
        "super","this","throw","true","try","typealias","typeof","val",
        "var","when","while","by","catch","constructor","delegate",
        "dynamic","field","file","finally","get","import","init",
        "param","property","receiver","set","setparam","value","where",
        "actual","abstract","annotation","companion","crossinline",
        "data","enum","expect","external","final","infix","inline",
        "inner","internal","lateinit","noinline","open","operator",
        "out","override","private","protected","public","reified",
        "sealed","suspend","tailrec","vararg",
    ]

    def _build_rules(self):
        kw = _fmt(PALETTE["keyword"],    bold=True)
        st = _fmt(PALETTE["string"])
        st2= _fmt(PALETTE["string2"])
        nm = _fmt(PALETTE["number"])
        cm = _fmt(PALETTE["comment"],    italic=True)
        fn = _fmt(PALETTE["function"],   bold=True)
        cl = _fmt(PALETTE["class_name"], bold=True)
        an = _fmt(PALETTE["decorator"])
        op = _fmt(PALETTE["operator"])

        for kw_text in self.KEYWORDS:
            self._add(r'\b' + kw_text + r'\b', kw)

        self._add(r'@\w+', an)
        self._add(r'\bclass\s+(\w+)', cl)
        self._add(r'\bfun\s+(\w+)', fn)
        self._add(r'\$\{[^}]+\}', st2)   # string templates
        self._add(r'""".*?"""', st)
        self._add(r'"[^"\\]*(\\.[^"\\]*)*"', st)
        self._add(r"'[^'\\]*(\\.[^'\\]*)*'", st)
        self._add(r'\b[0-9]+[LlFf]?\b', nm)
        self._add(r'[+\-*/%=<>!&|^~?:]+', op)
        self._add(r'//[^\n]*', cm)

        self._set_multiline_comment('/*', '*/')


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
class HTMLHighlighter(_BaseHighlighter):
    def _build_rules(self):
        tag  = _fmt(PALETTE["tag"],      bold=True)
        attr = _fmt(PALETTE["attr"])
        st   = _fmt(PALETTE["string"])
        cm   = _fmt(PALETTE["comment"],  italic=True)
        op   = _fmt(PALETTE["operator"])

        # HTML comments handled as multiline below
        # Tags
        self._add(r'</?[A-Za-z][A-Za-z0-9]*', tag)
        self._add(r'>', op)
        self._add(r'/>', op)
        # Attributes
        self._add(r'\b[a-zA-Z-]+(?=\s*=)', attr)
        # Strings
        self._add(r'"[^"]*"', st)
        self._add(r"'[^']*'", st)
        # Doctype
        self._add(r'<!DOCTYPE[^>]*>', cm)

        self._set_multiline_comment('<!--', '-->')


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
class CSSHighlighter(_BaseHighlighter):
    CSS_PROPERTIES = [
        "color","background","background-color","border","border-radius",
        "margin","padding","width","height","display","position","top",
        "left","right","bottom","flex","grid","font","font-size",
        "font-weight","font-family","text-align","overflow","opacity",
        "transform","transition","animation","box-shadow","z-index",
        "cursor","outline","content","visibility","float","clear",
        "list-style","text-decoration","line-height","letter-spacing",
        "white-space","word-break","pointer-events","gap","align-items",
        "justify-content","flex-direction","flex-wrap","grid-template",
    ]

    def _build_rules(self):
        sel  = _fmt(PALETTE["selector"],  bold=True)
        prop = _fmt(PALETTE["property"])
        st   = _fmt(PALETTE["string"])
        nm   = _fmt(PALETTE["number"])
        cm   = _fmt(PALETTE["comment"],   italic=True)
        op   = _fmt(PALETTE["operator"])
        kw   = _fmt(PALETTE["keyword"])

        # Selectors
        self._add(r'[.#]?[A-Za-z][A-Za-z0-9_-]*\s*(?=\{)', sel)
        self._add(r'::[a-z-]+', sel)     # pseudo-elements
        self._add(r':[a-z-]+', sel)      # pseudo-classes
        self._add(r'@[a-z-]+', kw)       # at-rules

        # Properties
        for p in self.CSS_PROPERTIES:
            self._add(r'\b' + re.escape(p) + r'\b', prop)

        # Values / units
        self._add(r'\b[0-9]+\.?[0-9]*(px|em|rem|%|vh|vw|pt|s|ms|deg)?\b', nm)
        # Hex colors
        self._add(r'#[0-9A-Fa-f]{3,8}\b', nm)
        # Strings
        self._add(r'"[^"]*"', st)
        self._add(r"'[^']*'", st)
        # Operators / punctuation
        self._add(r'[{}:;,]', op)

        self._set_multiline_comment('/*', '*/')


# ---------------------------------------------------------------------------
# Markdown  (used by the plain-text editor, not the rendered view)
# ---------------------------------------------------------------------------
class MarkdownHighlighter(_BaseHighlighter):
    def _build_rules(self):
        h   = _fmt(PALETTE["md_heading"],  bold=True)
        bd  = _fmt(PALETTE["md_bold"],     bold=True)
        it  = _fmt(PALETTE["md_italic"],   italic=True)
        cd  = _fmt(PALETTE["md_code"])
        lk  = _fmt(PALETTE["md_link"])
        cm  = _fmt(PALETTE["comment"],     italic=True)

        # Headings
        self._add(r'^#{1,6}\s.*$', h)
        # Bold  **…** or __…__
        self._add(r'\*\*[^*]+\*\*', bd)
        self._add(r'__[^_]+__',     bd)
        # Italic  *…* or _…_
        self._add(r'\*[^*]+\*', it)
        self._add(r'_[^_]+_',   it)
        # Inline code  `…`
        self._add(r'`[^`]+`', cd)
        # Links  [text](url)  or  [text][ref]
        self._add(r'\[[^\]]+\]\([^)]+\)', lk)
        self._add(r'\[[^\]]+\]\[[^\]]*\]', lk)
        # Images  ![alt](url)
        self._add(r'!\[[^\]]*\]\([^)]+\)', lk)
        # Blockquote
        self._add(r'^>\s.*$', cm)
        # Horizontal rule
        self._add(r'^[-*_]{3,}\s*$', cm)
        # List bullets
        self._add(r'^\s*[-*+]\s', _fmt(PALETTE["operator"]))
        self._add(r'^\s*\d+\.\s', _fmt(PALETTE["operator"]))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
EXTENSION_MAP: dict[str, type] = {
    # Python
    ".py":   PythonHighlighter,
    ".pyw":  PythonHighlighter,
    # Java
    ".java": JavaHighlighter,
    # JavaScript / TypeScript
    ".js":   JavaScriptHighlighter,
    ".jsx":  JavaScriptHighlighter,
    ".ts":   JavaScriptHighlighter,
    ".tsx":  JavaScriptHighlighter,
    ".mjs":  JavaScriptHighlighter,
    # Kotlin
    ".kt":   KotlinHighlighter,
    ".kts":  KotlinHighlighter,
    # Web
    ".html": HTMLHighlighter,
    ".htm":  HTMLHighlighter,
    ".css":  CSSHighlighter,
    # Markdown
    ".md":   MarkdownHighlighter,
    ".markdown": MarkdownHighlighter,
}

def get_highlighter(file_path: str, document) -> _BaseHighlighter | None:
    """
    Attach the right highlighter to *document* based on *file_path* extension.
    Returns the highlighter instance, or None if unsupported.
    """
    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    cls = EXTENSION_MAP.get(ext)
    if cls:
        return cls(document)
    return None


# ---------------------------------------------------------------------------
# Syntax checker  (returns list of dicts with line / message)
# ---------------------------------------------------------------------------
def check_syntax(file_path: str, source: str) -> list[dict]:
    """
    Run a best-effort syntax check.
    Returns a list of {"line": int, "col": int, "message": str, "severity": "error"|"warning"}
    """
    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

    if ext in (".py", ".pyw"):
        return _check_python(source)
    if ext in (".js", ".jsx", ".mjs"):
        return _check_js(source)
    if ext == ".java":
        return _check_java(source)
    return []


def _check_python(source: str) -> list[dict]:
    issues = []
    try:
        ast.parse(source)
    except SyntaxError as e:
        issues.append({
            "line": e.lineno or 1,
            "col":  e.offset or 0,
            "message": f"SyntaxError: {e.msg}",
            "severity": "error",
        })
    except Exception as e:
        issues.append({"line": 1, "col": 0, "message": str(e), "severity": "error"})

    # Basic style warnings
    for i, line in enumerate(source.splitlines(), 1):
        if line.rstrip() != line:
            issues.append({
                "line": i, "col": len(line.rstrip()),
                "message": "Trailing whitespace",
                "severity": "warning",
            })
        if "\t" in line:
            issues.append({
                "line": i, "col": line.index("\t"),
                "message": "Tab character (use spaces per PEP 8)",
                "severity": "warning",
            })
    return issues


def _check_js(source: str) -> list[dict]:
    issues = []
    lines = source.splitlines()

    # Unmatched brackets heuristic
    stack = []
    pairs = {")": "(", "}": "{", "]": "["}
    openers = set("({[")
    closers = set(")}]")

    in_string = False
    string_char = ""

    for i, line in enumerate(lines, 1):
        for j, ch in enumerate(line):
            if in_string:
                if ch == string_char and (j == 0 or line[j-1] != "\\"):
                    in_string = False
                continue
            if ch in ('"', "'", "`"):
                in_string = True
                string_char = ch
                continue
            if line[j:j+2] == "//":
                break
            if ch in openers:
                stack.append((ch, i, j))
            elif ch in closers:
                if stack and stack[-1][0] == pairs[ch]:
                    stack.pop()
                else:
                    issues.append({
                        "line": i, "col": j,
                        "message": f"Unexpected '{ch}'",
                        "severity": "error",
                    })

    for ch, ln, col in stack:
        issues.append({
            "line": ln, "col": col,
            "message": f"Unmatched '{ch}'",
            "severity": "error",
        })

    # semicolon warnings (very basic)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if (stripped
                and not stripped.startswith("//")
                and not stripped.endswith(("{", "}", ",", ";", "(", ")", "|", "&", "?", ":"))
                and not stripped.startswith(("if", "else", "for", "while", "function",
                                             "class", "//", "/*", "*", "import", "export",
                                             "return", "const", "let", "var"))
                and len(stripped) > 2):
            issues.append({
                "line": i, "col": len(line),
                "message": "Possible missing semicolon",
                "severity": "warning",
            })

    return issues


def _check_java(source: str) -> list[dict]:
    issues = []
    lines = source.splitlines()

    # Missing semicolons on statement lines
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if (stripped
                and not stripped.startswith("//")
                and not stripped.startswith("/*")
                and not stripped.startswith("*")
                and not stripped.endswith((";", "{", "}", ","))
                and not stripped.startswith(("@", "import", "package",
                                             "if", "else", "for", "while",
                                             "try", "catch", "finally", "class",
                                             "interface", "enum", "public", "private",
                                             "protected", "abstract", "static"))
                and len(stripped) > 2):
            issues.append({
                "line": i, "col": len(line),
                "message": "Possible missing semicolon",
                "severity": "warning",
            })

    # Class name should start uppercase
    for i, line in enumerate(lines, 1):
        m = re.search(r'\bclass\s+([a-z]\w*)', line)
        if m:
            issues.append({
                "line": i, "col": m.start(1),
                "message": f"Class '{m.group(1)}' should start with uppercase",
                "severity": "warning",
            })

    return issues