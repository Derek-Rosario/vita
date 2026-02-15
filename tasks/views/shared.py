from django.shortcuts import redirect
from django.urls import reverse

SHOW_PROJECTS_QUERY_PARAM = "show_projects"
SHOW_TAGS_QUERY_PARAM = "show_tags"


def redirect_to_board_with_query(param: str):
    return redirect(f"{reverse('task_board')}?{param}=1")
