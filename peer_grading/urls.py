from django.conf.urls import patterns, url, include
from rest_framework import routers
from views import EssayViewSet, StatusViewSet


router = routers.DefaultRouter()
router.register(r'essay', EssayViewSet)
router.register(r'status', StatusViewSet)

# Interface for communicating with the Peer Grading Module in LMS.
urlpatterns = patterns('',
                       url(r'^', include(router.urls)),
                       url(r'^api-auth/', include('rest_framework.urls', namespace='rest_framework'))
)