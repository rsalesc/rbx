import datetime

if __name__ == '__main__':
    from rbx.box.tooling.boca.scraper import BocaScraper

    # BASE_URL = 'http://137.184.1.39/boca'
    BASE_URL = 'http://localhost:8000/boca'

    system_scraper = BocaScraper(base_url=BASE_URL, username='system', password='boca')
    system_scraper.login()
    assert system_scraper.loggedIn
    system_scraper.create_and_activate_contest()

    admin_scraper = BocaScraper(base_url=BASE_URL, username='admin', password='boca')
    admin_scraper.login()
    assert admin_scraper.loggedIn
    admin_scraper.configure_contest(
        start_time=datetime.datetime.now() - datetime.timedelta(minutes=1)
    )
    admin_scraper.configure_main_site(autojudge=True, chief='judge')
