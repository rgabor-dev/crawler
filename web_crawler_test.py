
import unittest
import requests
from unittest.mock import Mock, patch
from web_crawler import WebContent, WebPage, RequestResult, WebPageException, UrlStore, WebCrawler


class UrlStoreTests(unittest.TestCase):

    def setUp(self):
        self.url_store = UrlStore()

    def test_pop_if_exists_with_urls(self):
        # add two urls to be processed
        urls = ["http://example.com/page1", "http://example.com/page2"]
        self.url_store.add_to_be_processed(urls)

        # take out three urls
        url1 = self.url_store.pop_if_exists()
        url2 = self.url_store.pop_if_exists()
        url3 = self.url_store.pop_if_exists()

        # first two urls should be the same that we put in
        self.assertEqual(sorted([url1, url2]), sorted(urls))

        # third url should be None
        self.assertIsNone(url3)

    def test_pop_if_exists_without_urls(self):
        # pop when no urls stored
        url = self.url_store.pop_if_exists()

        # url should be None
        self.assertIsNone(url)

    def test_add_to_be_processed(self):
        url1 = "http://example.com/page1"
        url2 = "http://example.com/page2"
        url3 = "http://example.com/page3"
        # set url1 as it was already visited
        self.url_store._visited.add(url1)
        # set url2 as it is being processed
        self.url_store._in_process.add(url2)

        # add all urls to be processed
        self.url_store.add_to_be_processed([url1, url2, url3])

        # only url3 should be added to be processed
        self.assertEqual(self.url_store._to_process, set([url3]))

    def test_add_failed(self):
        url = "http://example.com/page1"
        self.url_store._in_process.add(url)

        # set in_process url as failed
        self.url_store.add_failed(url)

        # url should be put to failed
        self.assertIn(url, self.url_store._failed)
        # url should be put to visited
        self.assertIn(url, self.url_store._visited)
        # url should be taken out from in_process
        self.assertNotIn(url, self.url_store._in_process)


    def test_num_of_visited(self):
        self.url_store._visited = set(["http://example.com/page1", "http://example.com/page2"])

        num_visited = self.url_store.num_of_visited()

        self.assertEqual(num_visited, 2)

    def test_num_of_all(self):
        self.url_store._to_process = set(["http://example.com/page1", "http://example.com/page2"])
        self.url_store._visited = set(["http://example.com/page3", "http://example.com/page4"])
        self.url_store._in_process = set(["http://example.com/page5"])

        num_all = self.url_store.num_of_all()

        self.assertEqual(num_all, 5)


class WebContentTests(unittest.TestCase):

    def setUp(self):
        self.url = "http://example.com"
        self.html_text = """
            <html>
            <body>
                <a href="/page1">Page 1</a>
                <a href="http://example.com/page2">Page 2</a>
                <a href="http://example.com/page3#section">Page 3</a>
                <a href="https://example.com/page4">Page 4</a>
                <a href="#section">Section</a>
                <a>This is not a link</a>
            </body>
            </html>
        """
        self.web_content = WebContent(self.url, self.html_text)

    def test_urls_with_defrag_true(self):
        expected_urls = [
            "http://example.com",
            "http://example.com/page1",
            "http://example.com/page2",
            "http://example.com/page3",
            "https://example.com/page4",
        ]
        urls = self.web_content.urls(url_defrag=True)
        self.assertEqual(sorted(urls), sorted(expected_urls))

    def test_urls_with_defrag_false(self):
        expected_urls = [
            "http://example.com#section",
            "http://example.com/page1",
            "http://example.com/page2",
            "http://example.com/page3#section",
            "https://example.com/page4",
        ]
        urls = self.web_content.urls(url_defrag=False)
        self.assertEqual(sorted(urls), sorted(expected_urls))


    def test_get_absolute_url_with_defrag_true(self):
        base_url = "http://example.com"
        relative_url = "/page1#section"
        absolute_url = self.web_content._get_absolute_url(base_url, relative_url, url_defrag=True)
        self.assertEqual(absolute_url, "http://example.com/page1")

    def test_get_absolute_url_with_defrag_false(self):
        base_url = "http://example.com"
        relative_url = "/page2#section"
        absolute_url = self.web_content._get_absolute_url(base_url, relative_url, url_defrag=False)
        self.assertEqual(absolute_url, "http://example.com/page2#section")


class WebPageTests(unittest.TestCase):

    def setUp(self):
        self.url = "http://example.com"
        self.max_retries = 3
        self.delay_sec = 1
        self.web_page = WebPage(self.url, self.max_retries, self.delay_sec)

    @patch("web_crawler.WebContent")
    @patch("web_crawler.WebPage._retry_request")
    def test_content(self, mock_retry_request, mock_web_content):
        expected_web_content = WebContent(self.url, "HTML content")
        mock_retry_request.return_value = "HTML content"
        mock_web_content.return_value = expected_web_content

        result = self.web_page.content()

        mock_retry_request.assert_called_once()
        mock_web_content.assert_called_once_with(self.url, "HTML content")
        self.assertEqual(result, expected_web_content)

    @patch("web_crawler.WebPage._request")
    @patch("time.sleep")
    def test_retry_request_success_on_first_try(self, mock_sleep, mock_request):
        mock_request.return_value = RequestResult(success=True, text_content="HTML content")

        result = self.web_page._retry_request()

        mock_request.assert_called_once()
        self.assertEqual(result, "HTML content")
        mock_sleep.assert_not_called()

    @patch("web_crawler.WebPage._request")
    @patch("time.sleep")
    def test_retry_request_success_on_second_try(self, mock_sleep, mock_request):
        mock_request.side_effect = [
            RequestResult(success=False),
            RequestResult(success=True, text_content="HTML content")
        ]

        result = self.web_page._retry_request()

        self.assertEqual(mock_request.call_count, 2)
        self.assertEqual(result, "HTML content")
        mock_sleep.assert_called_once_with(self.delay_sec)

    @patch("web_crawler.WebPage._request")
    @patch("time.sleep")
    def test_retry_request_max_retries_exceeded(self, mock_sleep, mock_request):
        mock_request.return_value = RequestResult(success=False)

        with self.assertRaises(WebPageException):
            self.web_page._retry_request()

        self.assertEqual(mock_request.call_count, self.max_retries)
        self.assertEqual(mock_sleep.call_count, self.max_retries)

    @patch("web_crawler.requests.get")
    def test_request_success(self, mock_requests_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"HTML content"
        mock_requests_get.return_value = mock_response

        result = self.web_page._request()

        mock_requests_get.assert_called_once_with(self.url)
        self.assertEqual(result.success, True)
        self.assertEqual(result.text_content, "HTML content")

    @patch("web_crawler.requests.get")
    @patch("web_crawler.print")
    def test_request_failed(self, mock_print, mock_requests_get):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_requests_get.return_value = mock_response

        result = self.web_page._request()

        mock_requests_get.assert_called_once_with(self.url)
        self.assertEqual(result.success, False)

    @patch("web_crawler.requests.get")
    @patch("web_crawler.print")
    def test_request_exception(self, mock_print, mock_requests_get):
        mock_requests_get.side_effect = requests.RequestException()

        result = self.web_page._request()

        mock_requests_get.assert_called_once_with(self.url)
        self.assertEqual(result.success, False)


class WebCrawlerTests(unittest.TestCase):

    def setUp(self):
        self.starting_url = "http://example.com"
        self.num_threads = 10
        self.web_crawler = WebCrawler(self.starting_url, self.num_threads)

    def test_is_same_domain_true(self):
        url = "http://example.com/page1"
        self.web_crawler._domain = "example.com"

        result = self.web_crawler._is_same_domain(url)

        self.assertTrue(result)

    def test_is_same_domain_false(self):
        url = "http://community.monzo.com"
        self.web_crawler._domain = "monzo.com"

        result = self.web_crawler._is_same_domain(url)

        self.assertFalse(result)


    def test_is_same_domain_false(self):
        url = "http://anotherdomain.com/page1"
        self.web_crawler._domain = "example.com"

        result = self.web_crawler._is_same_domain(url)

        self.assertFalse(result)

    def test_is_valid_url_true(self):
        url = "http://example.com/page1"

        result = self.web_crawler._is_valid_url(url)

        self.assertTrue(result)

    def test_is_valid_url_false_missing_scheme(self):
        url = "example.com/page1"

        result = self.web_crawler._is_valid_url(url)

        self.assertFalse(result)

    def test_is_valid_url_false_missing_netloc(self):
        url = "http:///page1"

        result = self.web_crawler._is_valid_url(url)

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()