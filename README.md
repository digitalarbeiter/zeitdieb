# Zeitdieb

_Zeitdieb_ allows you to profile the time each line of your code takes.

![Screenshot of the output of zeitdieb](https://raw.githubusercontent.com/digitalarbeiter/zeitdieb/master/screenshot.png)

```
pip install zeitdieb
```

## Manual usage

```python
with StopWatch(additional, callables) as sw:
    your()
    code()
print(sw)
```

Alternatively, without using the context manager:

```python
sw = StopWatch(additional, callables)
sw.start()
your()
code()
sw.finish()
print(sw)
```


## Formatting

While you can just print the `StopWatch` object, you can also customize the output by using f-strings:

```python
print(f"{sw:3b:0.3,0.1}")
```

The format spec looks like this: `[width][flags]:[threshold][,threshold]`.

- `width` specifies the width of the time column (e.g. `4` for an output like `2.01`)
- `flags` are single-letter flags influencing the output:
    - `b` enables barplot mode: Instead of a numeric time output, a vertical barplot will be printed
- `threshold`s specify where to start marking times as critical/warnings
  (red/yellow). The thresholds must be ordered (highest to lowest).

## Integrations

Zeitdieb can optionally be intregrated with Pyramid, Flask, or FastAPI. After
you've done so, you can trigger tracing with the special header `X-Zeitdieb`.

### Pyramid

Put this somewhere in your Pyramid settings:

```ini
zeitdieb.format = 20b

pyramid.tweens =
    ...
    zeitdieb.pyramid
```

### Flask

For Flask or flask-based frameworks, adjust your `create_app()` function:

```python
def create_app():
    ...
    my_flask_app.config["ZEITDIEB_FORMAT"] = "7b:0.5"
    zeitdieb.flask(my_flask_app)
```

### FastAPI

FastAPI can be configured by calling `zeitdieb.fastapi()` inside of `create_app()`:

```python
class Settings(...):
    ...
    zeitdieb_format: Optional[str] = "6b"

def create_app(...):
    ...
    zeitdieb.fastapi(app, settings)
```

### Settings client headers

To trigger the tracing of functions, you need to set an `X-Zeitdieb` header:

#### curl

```bash
$ curl https://.../ -H 'X-Zeitdieb: path.to.module:callable,path.to.othermodule:callable`
```

#### jsonrpclib

```python
jsonrpclib.ServerProxy(host, headers={"X-Zeitdieb": "path.to.module:callable,path.to.othermodule:callable"})
```

## Acknowledgements

This project was created as a result of a learning day @ [solute](https://www.solute.de/ger/).
