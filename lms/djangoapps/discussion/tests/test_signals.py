from django.test import TestCase
import mock

from django_comment_common import signals, models
from lms.djangoapps.discussion.config import PROFANITY_CHECKER_FLAG
from lms.djangoapps.discussion.signals.handlers import ENABLE_FORUM_NOTIFICATIONS_FOR_SITE_KEY
import openedx.core.djangoapps.request_cache as request_cache
from openedx.core.djangoapps.site_configuration.tests.factories import SiteFactory, SiteConfigurationFactory
from openedx.core.djangoapps.waffle_utils.testutils import override_waffle_flag
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory


class SendMessageHandlerTestCase(TestCase):
    shard = 4

    def setUp(self):
        course_id = 'course-v1:edX+DemoX+Demo_Course'
        self.sender = mock.Mock()
        self.user = mock.Mock()
        self.post = mock.Mock(course_id=course_id)
        self.post.thread.course_id = course_id

        self.site = SiteFactory.create()

    @mock.patch('lms.djangoapps.discussion.signals.handlers.get_current_site')
    @mock.patch('lms.djangoapps.discussion.signals.handlers.send_message')
    def test_comment_created_signal_sends_message(self, mock_send_message, mock_get_current_site):
        site_config = SiteConfigurationFactory.create(site=self.site)
        site_config.values[ENABLE_FORUM_NOTIFICATIONS_FOR_SITE_KEY] = True
        site_config.save()
        mock_get_current_site.return_value = self.site
        signals.comment_created.send(sender=self.sender, user=self.user, post=self.post)

        mock_send_message.assert_called_once_with(self.post, mock_get_current_site.return_value)

    @mock.patch('lms.djangoapps.discussion.signals.handlers.get_current_site', return_value=None)
    @mock.patch('lms.djangoapps.discussion.signals.handlers.send_message')
    def test_comment_created_signal_message_not_sent_without_site(self, mock_send_message, mock_get_current_site):
        signals.comment_created.send(sender=self.sender, user=self.user, post=self.post)

        self.assertFalse(mock_send_message.called)

    @mock.patch('lms.djangoapps.discussion.signals.handlers.get_current_site')
    @mock.patch('lms.djangoapps.discussion.signals.handlers.send_message')
    def test_comment_created_signal_msg_not_sent_without_site_config(self, mock_send_message, mock_get_current_site):
        mock_get_current_site.return_value = self.site
        signals.comment_created.send(sender=self.sender, user=self.user, post=self.post)

        self.assertFalse(mock_send_message.called)

    @mock.patch('lms.djangoapps.discussion.signals.handlers.get_current_site')
    @mock.patch('lms.djangoapps.discussion.signals.handlers.send_message')
    def test_comment_created_signal_msg_not_sent_with_site_config_disabled(
            self, mock_send_message, mock_get_current_site
    ):
        site_config = SiteConfigurationFactory.create(site=self.site)
        site_config.values[ENABLE_FORUM_NOTIFICATIONS_FOR_SITE_KEY] = False
        site_config.save()
        mock_get_current_site.return_value = self.site
        signals.comment_created.send(sender=self.sender, user=self.user, post=self.post)

        self.assertFalse(mock_send_message.called)


class CoursePublishHandlerTestCase(ModuleStoreTestCase):
    """
    Tests for discussion updates on course publish.
    """
    ENABLED_SIGNALS = ['course_published']

    def test_discussion_id_map_updates_on_publish(self):
        course_key_args = dict(org='org', course='number', run='run')
        course_key = self.store.make_course_key(**course_key_args)

        with self.assertRaises(models.CourseDiscussionSettings.DoesNotExist):
            models.CourseDiscussionSettings.objects.get(course_id=course_key)

        # create course
        course = CourseFactory(emit_signals=True, **course_key_args)
        self.assertEqual(course.id, course_key)
        self._assert_discussion_id_map(course_key, {})

        # create discussion block
        request_cache.clear_cache(name=None)
        discussion_id = 'discussion1'
        discussion_block = ItemFactory.create(
            parent_location=course.location,
            category="discussion",
            discussion_id=discussion_id,
        )
        self._assert_discussion_id_map(course_key, {discussion_id: str(discussion_block.location)})

    def _assert_discussion_id_map(self, course_key, expected_map):
        """
        Verifies the discussion ID map for the given course matches the expected value.
        """
        discussion_settings = models.CourseDiscussionSettings.objects.get(course_id=course_key)
        self.assertDictEqual(discussion_settings.discussions_id_map, expected_map)


class ProfanityCheckerHandlerTestCase(ModuleStoreTestCase):
    """
    Tests for handling of possibly profane posts.
    """
    def setUp(self):
        self.sender = mock.Mock()
        self.user = mock.Mock(id=123)
        self.post = mock.Mock(
            id='abc',
            title='the title',
            body='the body',
            type='thread or comment',
            course_id='course-v1:edX+DemoX+Demo_Course',
            user_id=123,
        )

    @mock.patch('lms.djangoapps.discussion.profanity_checker.check_for_profanity_and_report')
    @override_waffle_flag(PROFANITY_CHECKER_FLAG, active=False)
    def test_no_profanity_checking_without_course_waffle_flag(self, mock_check_for_profanity):
        signals.thread_created.send(sender=self.sender, user=self.user, post=self.post)
        signals.thread_edited.send(sender=self.sender, user=self.user, post=self.post)
        signals.comment_created.send(sender=self.sender, user=self.user, post=self.post)
        signals.comment_edited.send(sender=self.sender, user=self.user, post=self.post)

        self.assertFalse(mock_check_for_profanity.called)

    @mock.patch('lms.djangoapps.discussion.profanity_checker.check_for_profanity_and_report')
    @override_waffle_flag(PROFANITY_CHECKER_FLAG, active=True)
    def test_profanity_checking_occurs_with_course_waffle_flag(self, mock_check_for_profanity):
        signals.thread_created.send(sender=self.sender, user=self.user, post=self.post)
        signals.thread_edited.send(sender=self.sender, user=self.user, post=self.post)
        signals.comment_created.send(sender=self.sender, user=self.user, post=self.post)
        signals.comment_edited.send(sender=self.sender, user=self.user, post=self.post)

        expected_context = {
            'post_id': self.post.id,
            'post_title': self.post.title,
            'post_body': self.post.body,
            'post_type': self.post.type,
            'course_id': self.post.course_id,
        }
        mock_check_for_profanity.assert_has_calls([mock.call(**expected_context)] * 4)
