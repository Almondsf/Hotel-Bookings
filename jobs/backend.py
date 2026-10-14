"""
A database-backed backend for Django's task framework (django.tasks).

Tasks are defined and enqueued with the standard API:

    from django.tasks import task

    @task
    def send_email(...): ...

    send_email.enqueue(...)

and executed by `manage.py run_worker`. No Redis or broker needed.
"""
import json

from django.tasks.backends.base import BaseTaskBackend
from django.tasks.base import TaskResult, TaskResultStatus
from django.tasks.exceptions import TaskResultDoesNotExist
from django.utils.crypto import get_random_string
from django.utils.module_loading import import_string

from .models import BackgroundJob


def _json(value):
    # Store exactly what a worker will receive: JSON round-tripped values
    return json.loads(json.dumps(value))


class DatabaseBackend(BaseTaskBackend):
    supports_defer = True
    supports_priority = True
    supports_get_result = True

    def enqueue(self, task, args, kwargs):
        self.validate_task(task)
        job = BackgroundJob.objects.create(
            id=get_random_string(32),
            task_path=task.module_path,
            queue_name=task.queue_name,
            priority=task.priority,
            args=_json(list(args)),
            kwargs=_json(kwargs),
            run_after=task.run_after,
            max_attempts=self.options.get('MAX_ATTEMPTS', 5),
        )
        return self._result(job, task)

    def get_result(self, result_id):
        job = BackgroundJob.objects.filter(pk=result_id).first()
        if job is None:
            raise TaskResultDoesNotExist(result_id)
        return self._result(job, import_string(job.task_path))

    def _result(self, job, task):
        result = TaskResult(
            task=task, id=job.id, status=TaskResultStatus[job.status], enqueued_at=job.enqueued_at,
            started_at=job.started_at, last_attempted_at=job.started_at, finished_at=job.finished_at,
            args=job.args, kwargs=job.kwargs, backend=self.alias, errors=[],
            worker_ids=[job.worker_id] if job.worker_id else [],
        )
        object.__setattr__(result, '_return_value', job.return_value)
        return result
