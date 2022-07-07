from django.test import TestCase

from feeds.models import Feed


class TestFindFeedFromURL(TestCase):
    def assertIsPreserved(self, url):
        self.assertEqual(Feed.find_feed_from_url(url), url)

    def test_convert_surls(self):
        """
        Tests that Feed.find_feed_from_url returns the feed URL for common
        blogging websites.

        Also ensure that it preserves original feed URLS, respecting trailing
        slashes
        """

        self.assertIsPreserved("https://jack.bearblog.dev/feed/")
        self.assertEqual(
            Feed.find_feed_from_url("https://jack.bearblog.dev"),
            "https://jack.bearblog.dev/feed/",
        )

        self.assertIsPreserved("https://developer.wordpress.com/blog/feed/")
        self.assertEqual(
            Feed.find_feed_from_url("https://developer.wordpress.com/blog"),
            "https://developer.wordpress.com/blog/feed/",
        )

        self.assertIsPreserved("https://andrenader.substack.com/feed")
        self.assertEqual(
            Feed.find_feed_from_url("https://andrenader.substack.com"),
            "https://andrenader.substack.com/feed",
        )

        self.assertIsPreserved(
            "https://googleprojectzero.blogspot.com/feeds/posts/default"
        )
        self.assertEqual(
            Feed.find_feed_from_url("https://googleprojectzero.blogspot.com/"),
            "https://googleprojectzero.blogspot.com/feeds/posts/default",
        )

        self.assertIsPreserved("https://bradleylambertblog.tumblr.com/rss")
        self.assertEqual(
            Feed.find_feed_from_url(
                "https://bradleylambertblog.tumblr.com",
            ),
            "https://bradleylambertblog.tumblr.com/rss",
        )

        self.assertIsPreserved("https://medium.com/feed/@dropbox")
        self.assertEqual(
            Feed.find_feed_from_url("https://medium.com/@dropbox"),
            "https://medium.com/feed/@dropbox",
        )

        self.assertIsPreserved("https://starcodes-heartcodes.medium.com/feed")
        self.assertEqual(
            Feed.find_feed_from_url(
                "https://starcodes-heartcodes.medium.com",
            ),
            "https://starcodes-heartcodes.medium.com/feed",
        )

        self.assertIsPreserved("https://medium.com/feed/geekculture")
        self.assertEqual(
            Feed.find_feed_from_url("https://medium.com/geekculture"),
            "https://medium.com/feed/geekculture",
        )
