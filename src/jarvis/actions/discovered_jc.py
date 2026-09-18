def run(parameters: dict) -> str:
    import jc
    import json

    command = parameters.get('command', None)
    data = parameters.get('data', None)

    if command is None or data is None:
        return "Error: 'command' and 'data' parameters are required."

    parser_module_name = command.replace('-', '_')
    try:
        parser_module = jc.get_parser(parser_module_name)
        parsed_data = parser_module.parse(data)
        return json.dumps(parsed_data, indent=4)
    except Exception as e:
        return f"Error parsing {command}: {str(e)}"