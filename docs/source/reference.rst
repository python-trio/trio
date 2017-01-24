..
   Instrument API:

   class Instrument:
       def task_scheduled(self, task):
           pass

       def before_task_step(self, task):
           pass

       def after_task_step(self, task):
           pass

       def close(self):
           pass
