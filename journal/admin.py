from django.contrib import admin
from .models import DreamEntry, JournalEntry, MoodEntry

@admin.register(MoodEntry)
class MoodEntryAdmin(admin.ModelAdmin):
    list_display = ('datetime', 'mood', 'notes')
    list_filter = ('mood', 'datetime')
    search_fields = ('notes',)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('date', 'title')
    list_filter = ('date',)
    search_fields = ('title', 'content_markdown')


@admin.register(DreamEntry)
class DreamEntryAdmin(admin.ModelAdmin):
    list_display = ('date', 'type')
    list_filter = ('type', 'date')
    search_fields = ('content_markdown',)