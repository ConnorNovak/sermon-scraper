"""
Throwaway script: load a subsplash page in Playwright and print every
network request it makes, so you can see how the guest_token / core API
calls get discovered.
"""

from playwright.sync_api import sync_playwright

URL = "https://subsplash.com/u/calvarychapeltherock/media/l/a3f0dc4-matthew"

requests = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.on("request", lambda req: requests.append((req.resource_type, req.method, req.url)))

    page.goto(URL, wait_until="load")
    page.wait_for_timeout(3000)

    browser.close()

print(f"{len(requests)} requests captured\n")
for resource_type, method, url in requests:
    print(f"[{resource_type:10}] {method} {url}")

print("Only core/subsplash.com API calls:")
for resource_type, method, url in requests:
    if "core.subsplash.com" in url:
        print(f"[{resource_type:10}] {method} {url}")
