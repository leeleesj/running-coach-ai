.PHONY: api dashboard

api:
	uv run uvicorn app.main:app --reload --port 8000

dashboard:
	uv run streamlit run dashboard/main.py --server.port 8501
