def find_duplicates(numbers):
    seen = set()
    duplicates = set()
    for item in numbers:
        if item in seen:
            duplicates.add(item)
        else:
            seen.add(item)
    return list(duplicates)

data = list(range(3000)) + list(range(1000))
print(len(find_duplicates(data)))
