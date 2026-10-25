import hashlib
import urllib.request
import xml.etree.ElementTree as ET

url = "https://r.jina.ai/https://wlancer.substack.com/feed"
request = urllib.request.Request(url, headers={"X-Return-Format": "html", "X-No-Cache": "true"})
with urllib.request.urlopen(request, timeout=45) as response:
    body = response.read()
    root = ET.fromstring(body)
    print("Reader feed:", response.status, root.tag, root.findtext("channel/link"), len(root.findall("channel/item")), hashlib.sha256(body).hexdigest())
