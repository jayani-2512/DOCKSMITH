import streamlit as st
import os

st.title("Hello from Docksmith Container")

st.write("This app is running inside a container!")
st.info(os.environ.get("GREETING", "Hello"))

name = st.text_input("Enter your name:")

if name:
    st.success(f"Hello {name}, welcome to Docksmith!")
