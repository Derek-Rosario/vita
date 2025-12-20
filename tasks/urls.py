from django.urls import path

from . import views

urlpatterns = [
    path("board/", views.task_board, name="task_board"),
    path("board/fragment/", views.board_fragment, name="task_board_fragment"),
    path("board/move/", views.move_task, name="task_move"),
    path("add/", views.create_task, name="task_add"),
    path("quick-add/", views.quick_add_task, name="task_quick_add"),
    path("backlog/", views.task_backlog, name="task_backlog"),
    path(
        "backlog/<int:task_id>/promote/",
        views.promote_backlog_task,
        name="task_backlog_promote",
    ),
    path("tasks/", views.task_list, name="task_list"),
    path("projects/", views.project_list, name="project_list"),
    path("projects/add/", views.create_project, name="project_add"),
    path("projects/<int:project_id>/", views.project_detail, name="project_detail"),
    path("tags/", views.tag_list, name="tag_list"),
    path("tags/add/", views.create_tag, name="tag_add"),
    path("tags/<int:tag_id>/", views.tag_detail, name="tag_detail"),
    path("tags/<int:task_id>/activity", views.task_activity, name="task_activity"),
    path("task/<int:task_id>/edit/", views.edit_task, name="edit_task"),
    path("routines/", views.routine_list, name="routine_list"),
    path("routines/add/", views.routine_create, name="routine_add"),
    path("routines/<int:routine_id>/", views.routine_edit, name="routine_edit"),
    path(
        "routines/<int:routine_id>/delete/", views.routine_delete, name="routine_delete"
    ),
    path("routines/run/", views.routine_run, name="routine_run"),
    path(
        "routines/<int:routine_id>/run/",
        views.routine_run,
        name="routine_run_single",
    ),
]
