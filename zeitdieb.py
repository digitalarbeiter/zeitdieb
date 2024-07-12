import inspect
import io
import gc
import re
import sys
import importlib
from itertools import product
from collections import defaultdict, Counter
from time import monotonic
from math import log


class ColorPicker:
    COLOR_RANGE = {
        3: [
            (255, 0, 0),  # red
            (255, 215, 0),  # orange
            (255, 255, 200),  # yellow
            (0, 255, 0),  # green
        ],
        2: [
            (255, 0, 0),  # red
            (255, 215, 0),  # orange
            (0, 255, 0),  # green
        ],
        1: [
            (255, 0, 0),  # red
            (0, 255, 0),  # green
        ],
    }

    def __init__(self, thresholds):
        self.thresholds = thresholds
        self.colors = self.COLOR_RANGE[len(self.thresholds)]

    def __call__(self, value):
        if value >= self.thresholds[0]:
            # above highest threshold -> return "worst" color
            return self.colors[0]
        for start_color, stop_color, start, stop in zip(
            self.colors,
            self.colors[1:],
            self.thresholds,
            self.thresholds[1:] + [0],
        ):
            if start >= value >= stop:
                fraction = (value - start) / (stop - start)
                result = []
                # color calculation:
                # for each component (RGB), get the right point between the two colors
                for first, second in zip(start_color, stop_color):
                    diff = second - first
                    result.append(int(first + fraction * diff))
                return result
        # below lowest threshold -> return "best" color
        return self.colors[-1]


def colorize(value, color, background=None):
    r, g, b = color
    result = f"\x1b[38;2;{r};{g};{b}m{value}\x1b[0m"
    if background:
        # warning: log scale!
        r, g, b = background  # 0, 255, 255
        result = f"\x1b[48;2;{r};{g};{b}m{result}"
    return result


def format_time(time, *, precision, width):
    if time:
        return f"{time:{width}.{max(precision, 1)}f}"
    else:
        return " " * width


class TimeFormatter:
    def __init__(self, width, thresholds, *, flags=()):
        self.width = width
        self.thresholds = thresholds
        self.precision = width - 2
        self.max_time = None
        self.flags = flags
        self.color = ColorPicker(thresholds)

    def set_max(self, max_time):
        self.precision = self.width - (len(str(int(max_time))) + 1)
        self.max_time = max_time

    def __call__(self, time, *, final=False):
        if "b" in self.flags and not final:
            if "l" in self.flags and time != 0:
                size = int(log(1+time) / log(1+self.max_time) * (self.width * 8))
            else:
                size = int(time / self.max_time * (self.width * 8))
            full_blocks, last_block = divmod(size, 8)
            blocks = "█" * full_blocks + " ▏▎▍▌▋▊▉"[last_block].strip()
            result = f"{blocks:{self.width}}"
        else:
            result = format_time(
                time,
                precision=self.precision,
                width=self.width,
            )
        if final:
            result = f"\x1b[1m{result}"
            bg = None
        elif "l" in self.flags:
            bg = (128, 128, 128)
        else:
            bg = (0, 0, 0)
        return colorize(result, self.color(time), background=bg)


class StopWatch:
    def __init__(self, *trace):
        self.codes_to_trace = {f.__code__ for f in trace}
        self.lines = {}
        self.offset = {}
        self.times = defaultdict(Counter)
        self.t_last = {}
        self.l_last = {}
        self.open_frames = set()
        self.result = None

    def start(self):
        sys.settrace(self.trace_scope)

    def __enter__(self):
        frame = sys._getframe(1)
        self.start()
        frame.f_trace = self.trace_line
        self.prepare_frame(frame)
        return self

    def __exit__(self, exc_inst, exc_type, tb):
        self.finish()

    def prepare_frame(self, frame):
        code = frame.f_code
        self.lines[code], self.offset[code] = inspect.getsourcelines(frame)
        self.l_last[code] = frame.f_lineno
        self.t_last[code] = monotonic()

    def trace_line(self, frame, event, _arg):
        code = frame.f_code
        if event == "line":
            t_now = monotonic()
            self.open_frames.add(frame)
            self.times[code][self.l_last[code]] += t_now - self.t_last[code]
            self.l_last[code] = frame.f_lineno
            self.t_last[code] = monotonic()
            return self.trace_line
        if event == "return":
            self.finish_frame(frame)
        return None

    def trace_scope(self, frame, _event, _arg):
        if frame.f_code in self.codes_to_trace:
            self.prepare_frame(frame)
            return self.trace_line
        return None

    def finish_frame(self, frame):
        t_now = monotonic()
        code = frame.f_code
        self.times[code][self.l_last[code]] += t_now - self.t_last[code]
        self.open_frames.remove(frame)

    def finish(self):
        for leftover in list(self.open_frames):
            self.finish_frame(leftover)
        sys.settrace(None)
        self.result = {}
        for code in self.times:
            lines = []
            min_indent = min(len(line) - len(line.lstrip()) for line in self.lines[code])
            for lno, line in enumerate(self.lines[code], start=1):
                count = self.times[code][lno + self.offset[code]]
                lines.append((lno + self.offset[code], count, line.rstrip()[min_indent:]))
            self.result[code] = lines

    @staticmethod
    def code_name(code):
        try:
            return next(
                ref for ref in gc.get_referrers(code) if callable(ref)
            ).__qualname__
        except (StopIteration, AttributeError):
            return code.co_name

    def __format__(self, fmt):
        if not self.result:
            return repr(self)

        fmt, _, thresholds = fmt.partition(":")
        fmt, _, min_duration = fmt.partition(">")
        if min_duration:
            min_duration = float(min_duration)
        numlen = len(fmt) - len(fmt.lstrip("0123456789"))
        width, flags = fmt[:numlen], fmt[numlen:]
        flags = set(flags)
        if "b" not in flags and "l" in flags:
            flags.remove("l")
        if width:
            width = int(width)
        else:
            width = 5

        if thresholds:
            thresholds = [float(t) for t in thresholds.split(",")]
        else:
            thresholds = [0.1, 0.01]

        formatter = TimeFormatter(width, thresholds, flags=flags)

        buffer = io.StringIO()
        for code, lines in self.result.items():
            total = sum(t for _, t, _ in lines)
            if min_duration and total <= min_duration:
                continue
            buffer.write(f"Timings in \x1b[1m{colorize(self.code_name(code), (0, 255, 255))}")
            if "l" in flags:
                buffer.write(" (log scale)")
            buffer.write(":\n")
            formatter.set_max(max(time for _, time, _ in lines))
            max_lno_len = len(str(max(lno for lno, _, _ in lines)))
            gap_marker_needed = False
            for lno, time, line in lines:
                if flags & {*"qQ"} and time <= thresholds[-1]:
                    if "q" in flags:
                        gap_marker_needed = True
                    continue
                if gap_marker_needed:
                    buffer.write("⋮\n")
                    gap_marker_needed = False
                buffer.write(f"{formatter(time)} {lno:{max_lno_len}d} {line}\n")
            if gap_marker_needed:
                buffer.write("⋮\n")
                gap_marker_needed = False
            buffer.write("─" * width + "\n")
            buffer.write(f"{formatter(total, final=True)}\n\n")
        return buffer.getvalue().strip()

    def __str__(self):
        return self.__format__("3")

    def __repr__(self):
        return f"<{type(self).__name__} ({'un'*(not self.result) + 'finished'})>"


def load_dotted(spec):
    module_path, _, callable_name = spec.partition(":")
    spec = importlib.util.find_spec(module_path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    for attribute in callable_name.split("."):
        result = getattr(result, attribute)
    return result


def expand_braces(text, seen=None):
    # credits: Jim Pivarski
    if "," in text and text[0] != "{":
        text = f"{{{text}}}"
    if seen is None:
        seen = set()

    spans = [m.span() for m in re.finditer(r"\{[^\{\}]*\}", text)][::-1]
    alts = [text[start + 1 : stop - 1].split(",") for start, stop in spans]

    if len(spans) == 0:
        if text not in seen:
            yield text
        seen.add(text)

    else:
        for combo in product(*alts):
            replaced = list(text)
            for (start, stop), replacement in zip(spans, combo):
                replaced[start:stop] = replacement

            yield from expand_braces("".join(replaced), seen)


def get_functions_to_trace(headers):
    return [load_dotted(spec) for spec in expand_braces(headers["X-Zeitdieb"])]


def pyramid(handler, registry):
    """
    Somewhere in your Pyramid settings:

    zeitdieb.format = 20b

    pyramid.tweens =
        ...
        zeitdieb.pyramid
    """
    fmt = registry.settings.get("zeitdieb.format", "")

    def tween(request):
        if "X-Zeitdieb" not in request.headers:
            return handler(request)

        sw = StopWatch(*get_functions_to_trace(request.headers))
        sw.start()
        res = handler(request)
        sw.finish()
        print(f"{sw:{fmt}}")
        return res

    return tween


def flask(app):
    """
    def create_app():
        ...
        my_flask_app.config["ZEITDIEB_FORMAT"] = "7b:0.5"
        zeitdieb.flask(my_flask_app)
    """
    import flask

    fmt = app.config.get("ZEITDIEB_FORMAT", "")

    @app.before_request
    def before():
        if "X-Zeitdieb" not in flask.request.headers:
            return
        flask.g.sw = StopWatch(*get_functions_to_trace(flask.request.headers))
        flask.g.sw.start()

    @app.after_request
    def after(response):
        flask.g.sw.finish()
        print(f"{flask.g.sw:{fmt}}")
        return response


def fastapi(app, settings=None):
    """
    class Settings(...):
        ...
        zeitdieb_format: Optional[str] = "6b"

    def create_app(...):
        ...
        zeitdieb.fastapi(app, settings)
    """
    fmt = getattr(settings, "zeitdieb_format", "")

    @app.middleware("http")
    async def fastapi_middleware(request, call_next):
        if "X-Zeitdieb" not in request.headers:
            return await call_next(request)
        sw = StopWatch(*get_functions_to_trace(request.headers))
        sw.start()
        response = await call_next(request)
        sw.finish()
        print(f"{sw:{fmt}}")
        return response


if __name__ == "__main__":
    from time import sleep

    with StopWatch() as sw:
        sleep(0.1)
        sleep(0.2)
        sleep(0.3)
        sleep(0.4)
        sleep(0.5)
        sleep(0.6)
        sleep(0.7)
        sleep(0.8)
        sleep(0.9)
    print(f"{sw:2b:0.6,0.3}")
