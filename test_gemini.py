from google import genai
import os

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

code = """
def find_duplicates(items):
    result = []
    for i in items:
        for j in items:
            if i == j and i not in result:
                result.append(i)
    return result
"""

prompt = f"""
You are a code efficiency analyzer.

Analyze this code:
{code}

Tell me:
1. What is inefficient?
2. Why is it inefficient?
3. What is a better approach?
4. Give improved code.
"""

response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt
)

print(response.text)