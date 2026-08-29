import math

x = [10, 12, 14, 15, 19]
y = [20, 21, 25, 27, 30]


def mean(a):
    return sum(a) / len(a)


def variance(a):
    m = mean(a)
    return sum((v - m) ** 2 for v in a) / len(a)


def covariance(a, b):
    ma = mean(a)
    mb = mean(b)

    return sum(
        (x - ma) * (y - mb)
        for x, y in zip(a, b)
    ) / len(a)


def correlation(a, b):
    return covariance(a, b) / math.sqrt(
        variance(a) * variance(b)
    )


print("Mean X:", mean(x))
print("Variance X:", variance(x))
print("Covariance:", covariance(x, y))
print("Correlation:", correlation(x, y))
