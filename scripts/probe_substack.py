import urllib.request
from curl_cffi import requests

url = "https://wlancer.substack.com/feed"
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=15) as response:
        print("urllib:", response.status, response.headers.get("content-type"), len(response.read()))
except Exception as error:
    print("urllib:", str(error))

for target in (url, url + "?format=xml", "https://wlancer.substack.com/api/v1/archive?sort=new&offset=0&limit=10"):
    try:
        response = requests.get(target, impersonate="chrome", timeout=15)
        print(target, response.status_code, response.headers.get("server"), response.headers.get("content-type"), len(response.content), response.text[:180])
    except Exception as error:
        print(target, str(error))
