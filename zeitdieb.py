import inspect
import io
import gc
import sys
import importlib
from collections import defaultdict, Counter
from time import monotonic


class ColorPicker:
    def __init__(self, thresholds):
        self.thresholds = thresholds

    def __call__(self, value):
        for threshold, color in zip(
            self.thresholds,
            [
                31,  # red
                33,  # yellow
            ],
        ):
            if value > threshold:
                return color
        return 0


def colorize(value, color):
    return f"\x1b[{color}m{value}\x1b[0m"


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
            size = int(time / self.max_time * (self.width * 8))
            full_blocks, last_block = divmod(size, 8)
            blocks = "█"*full_blocks + " ▏▎▍▌▋▊▉"[last_block].strip()
            result = f"{blocks:{self.width}}"
        else:
            result = format_time(
                time,
                precision=self.precision,
                width=self.width,
            )
        if final:
            result = f"\x1b[1m{result}"
        return colorize(result, self.color(time))

class StopWatch:
    def __init__(self, *, trace=()):
        self.codes_to_trace = {f.__code__ for f in trace}
        self.lines = {}
        self.offset = {}
        self.times = defaultdict(Counter)
        self.t_last = {}
        self.l_last = {}
        self.open_frames = set()
        self.result = None
        sys.settrace(self.trace_scope)

    def prepare_frame(self, frame):
        code = frame.f_code
        self.lines[code], self.offset[code] = inspect.getsourcelines(frame)
        self.l_last[code] = frame.f_lineno
        self.t_last[code] = monotonic()

    def trace_line(self, frame, event, _arg):
        # print("tracing", frame, event, arg)
        code = frame.f_code
        if event == "line":
            self.open_frames.add(frame)
            t_now = monotonic()
            self.times[code][self.l_last[code]] += t_now - self.t_last[code]
            self.l_last[code] = frame.f_lineno
            self.t_last[code] = monotonic()
            return self.trace_line
        if event == "return":
            self.finish_frame(frame)
        return None

    def trace_scope(self, frame, _event, _arg):
        # print("stracing", frame, event, arg)
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
            for lno, line in enumerate(self.lines[code]):
                count = self.times[code][lno + self.offset[code]]
                lines.append((lno + self.offset[code], count, line.rstrip()))
            self.result[code] = lines

    @staticmethod
    def code_name(code):
        try:
            return next(ref for ref in gc.get_referrers(code) if callable(ref)).__qualname__
        except (StopIteration, AttributeError):
            return code.co_name

    def __format__(self, fmt):
        if not self.result:
            return repr(self)

        # <width>[p][:(1.22(,2.33)?]
        fmt, _, thresholds = fmt.partition(":")
        numlen = len(fmt) - len(fmt.lstrip("0123456789"))
        width, flags = fmt[:numlen], fmt[numlen:]
        flags = set(flags)
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
            total = 0
            buffer.write(f"Timings in {colorize(self.code_name(code), '1;36')}:\n")
            formatter.set_max(max(time for _, time, _ in lines))
            max_lno_len = len(str(max(lno for lno, _, _ in lines)))
            for lno, time, line in lines:
                buffer.write(f"{formatter(time)} {lno:{max_lno_len}d} {line}\n")
                total += time
            buffer.write("─"*width + "\n")
            buffer.write(f"{formatter(total, final=True)}\n\n")
        return buffer.getvalue().strip()

    def __str__(self):
        return self.__format__("3")

    def __repr__(self):
        return f"<{type(self).__name__} ({'un'*(not self.result) + 'finished'})>"


    @classmethod
    def install(cls, *functions_to_trace):
        frame = sys._getframe(1)
        stopwatch = cls(trace=functions_to_trace)
        frame.f_trace = stopwatch.trace_line
        stopwatch.prepare_frame(frame)
        return stopwatch


def load_dotted(spec):
    module_path, _, callable_name = spec.partition(":")
    spec = importlib.util.find_spec(module_path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    for attribute in callable_name.split("."):
        result = getattr(result, attribute)
    return result


def get_functions_to_trace(headers):
    specs = headers["X-Zeitdieb"].split(",")
    return [load_dotted(spec) for spec in specs]


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

        sw = StopWatch(trace=get_functions_to_trace(request.headers))
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
        flask.g.sw = StopWatch(trace=get_functions_to_trace(flask.request.headers))

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
    print("wit")
    fmt = getattr(settings, "zeitdieb_format", "")

    @app.middleware("http")
    async def fastapi_middleware(request, call_next):
        print("wat")
        if "X-Zeitdieb" not in request.headers:
            return await call_next(request)
        print("wot")
        sw = StopWatch(trace=get_functions_to_trace(request.headers))
        response = await call_next(request)
        sw.finish()
        print("wut")
        print(f"{sw:{fmt}}")
        return response


if __name__ == "__main__":
    from time import sleep
    def foo():
        sw = StopWatch.install(bar)
        sleep(0.1)
        sleep(0.3)
        bar()
        sleep(0.2)
        sw.finish()
        print(f"{sw:7b:0.2,0.1}")

    def bar():
        for _ in range(5):
            sleep(0.1)

    foo()
