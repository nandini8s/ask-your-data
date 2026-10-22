from tools import get_schema, run_sql

print(get_schema())
print("---")
print(run_sql("SELECT COUNT(*) FROM readings"))
print("---")
print(run_sql("SELECT * FROM zebra"))
print("---")
print(run_sql("DROP TABLE readings"))
print("---")
print(run_sql("SELECT 1; DROP TABLE readings"))
print("---")
print(run_sql("SELECT * FROM readings"))
print(run_sql("SELECT 1;"))        # trailing semicolon should work
print(run_sql("  select 1"))       # lowercase and leading spaces
print(run_sql("""SELECT b.name, ROUND(AVG(r.kwh),1)
FROM readings r JOIN buildings b ON b.id = r.building_id
WHERE CAST(substr(r.reading_time,12,2) AS INTEGER) < 5
GROUP BY b.name ORDER BY 2 DESC"""))
