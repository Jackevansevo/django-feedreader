from django.test import TestCase

from feeds.crawler import translate_common_feed_extensions


class TestFindFeedFromURL(TestCase):
    def assertIsPreserved(self, url):
        self.assertEqual(translate_common_feed_extensions(url), url)

    def test_converts_urls(self):
        """
        Tests that translate_common_feed_extensions returns the feed URL for common
        blogging websites.

        Also ensure that it preserves original feed URLS, respecting trailing
        slashes
        """

        self.assertIsPreserved("https://jack.bearblog.dev/feed/")
        self.assertEqual(
            translate_common_feed_extensions("https://jack.bearblog.dev"),
            "https://jack.bearblog.dev/feed/",
        )

        self.assertIsPreserved("https://developer.wordpress.com/blog/feed/")
        self.assertEqual(
            translate_common_feed_extensions("https://developer.wordpress.com/blog"),
            "https://developer.wordpress.com/blog/feed/",
        )

        self.assertIsPreserved("https://andrenader.substack.com/feed")
        self.assertEqual(
            translate_common_feed_extensions("https://andrenader.substack.com"),
            "https://andrenader.substack.com/feed",
        )

        self.assertIsPreserved(
            "https://googleprojectzero.blogspot.com/feeds/posts/default"
        )
        self.assertEqual(
            translate_common_feed_extensions("https://googleprojectzero.blogspot.com/"),
            "https://googleprojectzero.blogspot.com/feeds/posts/default",
        )

        self.assertIsPreserved("https://bradleylambertblog.tumblr.com/rss")
        self.assertEqual(
            translate_common_feed_extensions(
                "https://bradleylambertblog.tumblr.com",
            ),
            "https://bradleylambertblog.tumblr.com/rss",
        )

        self.assertIsPreserved("https://medium.com/feed/@dropbox")
        self.assertEqual(
            translate_common_feed_extensions("https://medium.com/@dropbox"),
            "https://medium.com/feed/@dropbox",
        )

        self.assertIsPreserved("https://starcodes-heartcodes.medium.com/feed")
        self.assertEqual(
            translate_common_feed_extensions(
                "https://starcodes-heartcodes.medium.com",
            ),
            "https://starcodes-heartcodes.medium.com/feed",
        )

        self.assertIsPreserved("https://medium.com/feed/geekculture")
        self.assertEqual(
            translate_common_feed_extensions("https://medium.com/geekculture"),
            "https://medium.com/feed/geekculture",
        )
