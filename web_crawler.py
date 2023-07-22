import time
import requests
import threading

from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup, SoupStrainer
from dataclasses import dataclass
from typing import List


class WebPageException(Exception):
    pass


@dataclass
class RequestResult:
    success: bool = True
    text_content: str = ""


class WebContent:
    """
    A class for processing HTML text and getting all the urls from it.
    """

    def __init__(self, url: str, html_text: str):
        self._url = url
        self._html_text = html_text


    def urls(self, url_defrag: bool = True) -> List[str]:
        soup = BeautifulSoup(self._html_text, "html.parser", parse_only=SoupStrainer("a"))
        return [
            self._get_absolute_url(self._url, link["href"], url_defrag)
            for link in soup
            if link.has_attr("href")
        ]

    def _get_absolute_url(self, base_url: str, relative_url: str, url_defrag: bool) -> str:
        absolute_url = urljoin(base_url, relative_url)
        if url_defrag:
            # removing the # section from the end of the url
            absolute_url = urldefrag(absolute_url).url
        return absolute_url


class WebPage:
    """
    A class for opening a web page and getting it's content in a form of WebContent.
    """

    def __init__(self, url: str,  max_retries: int = 3, delay_sec: int = 1):
        self._url = url
        self._max_retries = max_retries
        self._delay_sec = delay_sec

    def content(self) -> WebContent:
        return WebContent(self._url, self._retry_request())

    def _retry_request(self) -> str:
        retries = 0
        while retries < self._max_retries:
            result = self._request()
            if result.success:
                return result.text_content

            time.sleep(self._delay_sec)
            retries += 1

        raise WebPageException(f"Failed to process: {self._url}")

    def _request(self) -> RequestResult:
        try:
            response = requests.get(self._url)
            if response.status_code == 200:
                content = response.content.decode(encoding="iso-8859-1")
                return RequestResult(text_content=content)
        except requests.RequestException as e:
            pass

        return RequestResult(success=False)


class UrlStore:
    """
    A thread safe class to store all the urls that we are processing.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # all the urls that needs to be processed
        self._to_process = set()

        # urls that are currently being processed
        self._in_process = set()

        # all visited urls, even if we failed processing
        self._visited = set()

        # failed urls
        self._failed = []

    def pop_if_exists(self) -> str | None:
        """
        Returns a url that need to be processed or returns None if empty.
        """
        with self._lock:
            if len(self._to_process) == 0:
                return None

            # get and remove one item
            url = self._to_process.pop()

            # Add it to a temporary set so other threads won't add it
            # back while we are processing it.
            self._in_process.add(url)

            return url

    def set_processed(self, url: str) -> None:
        """
        Set the url to visited when done processing.
        """
        with self._lock:
            self._set_processed(url)

    def add_to_be_processed(self, urls: List[str]) -> None:
        with self._lock:
            # remove the visited urls
            new_urls = set(urls) - self._visited - self._in_process

            # add the new urls to be processed
            self._to_process =  self._to_process.union(new_urls)

    def add_failed(self, url: str) -> None:
        with self._lock:
            # add url to the failed list
            self._failed.append(url)

            # after failing we done processing the url
            self._set_processed(url)

    def num_of_visited(self) -> int:
        with self._lock:
            return len(self._visited)

    def num_of_all(self) -> int:
        with self._lock:
            return len(self._to_process) + len(self._visited) + len(self._in_process)

    def _set_processed(self, url: str) -> None:
        self._in_process.remove(url)
        self._visited.add(url)


class WebCrawler:
    def __init__(self, starting_url, num_threads=5):
        self._starting_url = starting_url
        self._num_threads = num_threads
        self._domain = urlparse(starting_url).netloc
        self._print_lock = threading.Lock()
        self._url_store = UrlStore()

    def crawl(self) -> None:
        # add the starting url to the url_store
        self._url_store.add_to_be_processed([self._starting_url])

        # pop the url from the url_store and process it
        self._process_page(self._url_store.pop_if_exists())

        # start the threads to process the rest of the urls
        self._wait_for_threads(self._create_threads())

    def _create_threads(self) -> List[threading.Thread]:
        threads = []
        for _ in range(self._num_threads):
            thread = threading.Thread(target=self._process_all_pages)
            thread.daemon = True
            thread.start()
            threads.append(thread)
        return threads

    def _wait_for_threads(self, threads: List[threading.Thread]) -> None:
        try:
            # wait for keyboard interrupt or the threads to finish
            while any([thread.is_alive() for thread in threads]):
                for thread in threads:
                    if thread.is_alive():
                        thread.join(1)
        except KeyboardInterrupt:
            print("Keyboard interrupt received. Stopping crawler threads...")

    def _process_all_pages(self) -> None:
        """
        The thread function to process all the urls from the url_store.
        Only stop when there are no more urls to be processed.
        """
        while True:
            url = self._url_store.pop_if_exists()
            if not url:
                break

            try:
                self._process_page(url)
            except WebPageException as exception:
                print(exception)
                self._url_store.add_failed(url)

    def _process_page(self, url: str) -> List[str]:
        # extract all urls form the page
        found_urls = WebPage(url).content().urls(url_defrag=True)

        # remove duplicates
        all_urls = list(set(found_urls))

        # filter for only valid urls
        all_urls = list(filter(self._is_valid_url, all_urls))

        # filter the urls for the exact same domain
        same_domain_urls = list(filter(self._is_same_domain, all_urls))

        # url is processed, set it in the url_store
        self._url_store.set_processed(url)

        # add the newly found urls to the url_store
        self._url_store.add_to_be_processed(same_domain_urls)

        # print out the results
        self._print_results(url, all_urls)


    def _is_same_domain(self, url: str) -> bool:
       return urlparse(url).netloc == self._domain

    def _is_valid_url(self, url: str) -> bool:
        parsed_url = urlparse(url)
        return bool(parsed_url.scheme and parsed_url.netloc)

    def _print_results(self, url: str, urls: List[str]) -> None:
        with self._print_lock:
            num_of_visited = self._url_store.num_of_visited()
            num_to_process = self._url_store.num_of_all()

            print(f"[{num_of_visited}/{num_to_process}] Processing: {url}")
            for url in sorted(urls):
                print(f"  {url}")


if __name__ == "__main__":
    crawler = WebCrawler("https://www.nba.com/")
    crawler.crawl()
