from rest_framework import serializers

from .models import Game


class GameSerializer(serializers.ModelSerializer):
    platforms = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")
    # Display names, same order as `platforms` (e.g. "PlayStation 5").
    platform_names = serializers.SlugRelatedField(source="platforms", many=True, read_only=True, slug_field="name")

    class Meta:
        model = Game
        fields = ["id", "name", "mono", "genre", "hue", "deep", "platforms", "platform_names", "max_players"]
