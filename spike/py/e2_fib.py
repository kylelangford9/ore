def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)
def sign(n):
    return -1 if n < 0 else 0 if n == 0 else 1
