zim-plugin: tasklist-eds.py

This plugin list the tasks of evolutoin data server via a dbus service of interface:

```
node /org/gnome/Shell/TaskListServer {
  interface org.freedesktop.DBus.Properties {
    methods:
      Get(in  s interface_name,
          in  s property_name,
          out v value);
      GetAll(in  s interface_name,
             out a{sv} properties);
      Set(in  s interface_name,
          in  s property_name,
          in  v value);
    signals:
      PropertiesChanged(s interface_name,
                        a{sv} changed_properties,
                        as invalidated_properties);
    properties:
  };
  interface org.freedesktop.DBus.Introspectable {
    methods:
      Introspect(out s xml_data);
    signals:
    properties:
  };
  interface org.freedesktop.DBus.Peer {
    methods:
      Ping();
      GetMachineId(out s machine_uuid);
    signals:
    properties:
  };
  interface org.gnome.Shell.TaskListServer {
    methods:
      GetTasks(in  b force_reload,
               out a(sssxxxa{sv}) tasks);
    signals:
      Changed();
    properties:
      readonly b HasTaskLists = true;
  };
};
```
