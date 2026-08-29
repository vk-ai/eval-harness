from eval_harness import Harness, Task, contains

tasks = [
    Task("capitals", "Capital of Kenya?", "Nairobi", contains),
    Task("math", "12*12", "144"),
]
h = Harness(tasks)
results = h.run(lambda p: "Nairobi" if "Kenya" in p else "144")
print(h.report(results))
