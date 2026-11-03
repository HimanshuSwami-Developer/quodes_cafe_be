from rest_framework import serializers

from .models import Game


class GameSerializer(serializers.ModelSerializer):
    platforms = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")
    # Display names, same order as `platforms` (e.g. "PlayStation 5").
    platform_names = serializers.SlugRelatedField(source="platforms", many=True, read_only=True, slug_field="name")
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ["id", "name", "mono", "genre", "hue", "deep", "platforms", "platform_names", "max_players",
                  "cover_url"]

    def get_cover_url(self, g):
        return file_url(g.cover, self.context.get("request"))


def file_url(f, request=None):
    """Absolute URL of an uploaded file, or None. Cloudinary URLs are already absolute."""
    if not f:
        return None
    url = f.url
    if not url.startswith("/"):
        return url
    if request is not None:
        return request.build_absolute_uri(url)
    from django.conf import settings
    return settings.SITE_URL + url
