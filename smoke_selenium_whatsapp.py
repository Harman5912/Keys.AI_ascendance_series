"""Real smoke test for the Selenium WhatsApp backend (not unit tests)."""
import time
import selenium
print(f"selenium {selenium.__version__}")
from whatsapp.selenium_client import SeleniumWhatsAppClient, SeleniumDriver
client = SeleniumWhatsAppClient(log=lambda m: print(" [log]", m))
driver = SeleniumDriver(client, log=lambda m: print(" [log]", m))
launched = False
try:
    print("\n--- launching real Chrome (persistent profile) ---")
    t0 = time.time()
    client.ensure_launched()
    print(f"launch took {time.time() - t0:.1f}s")
    time.sleep(6.0)
    print("\n--- health ---")
    print(client.health())
    print("\n--- page state ---")
    print("url   :", driver.page_url())
    print("title :", driver.page_title())
    print("pane  :", driver.message_pane_visible())
    print("composer:", driver.composer_ready())
    launched = True
    print("\nSMOKE OK - real Chrome reached WhatsApp Web")
finally:
    if launched:
        client.close()
        print("browser closed cleanly")
